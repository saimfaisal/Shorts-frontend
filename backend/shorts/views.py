from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from threading import Thread
from typing import Any, TypedDict, cast

from django.conf import settings
from django.core.files import File
from django.db import close_old_connections
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ShortVideo
from .serializers import ShortGenerationRequestSerializer, ShortVideoSerializer

logger = logging.getLogger(__name__)


class _ShortGenerationPayloadRequired(TypedDict):
    youtube_url: str
    duration: int


class _ShortGenerationPayload(_ShortGenerationPayloadRequired, total=False):
    start_time: int
    overlay_text: str  # New: text overlay provided by user


class ShortGenerateView(APIView):
    """Handle creation of short videos from YouTube sources."""

    def post(self, request, *args, **kwargs):
        request_serializer = ShortGenerationRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = cast(_ShortGenerationPayload, request_serializer.validated_data)

        if not can_reach_youtube():
            return Response(
                {"message": "Unable to reach YouTube. Check your internet connection and try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        start_time = payload.get("start_time", 0)
        overlay_text = payload.get("overlay_text", "My Short Video")  # Default text

        short = ShortVideo.objects.create(
            youtube_url=payload["youtube_url"],
            duration=payload["duration"],
            start_time=start_time,
            status=ShortVideo.STATUS_PROCESSING,
        )
        self._start_background_processing(short.pk, overlay_text)

        response_serializer = ShortVideoSerializer(short, context={"request": request})
        return Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)

    @staticmethod
    def _start_background_processing(short_id: int, overlay_text: str) -> None:
        def _worker() -> None:
            close_old_connections()
            try:
                short_instance = ShortVideo.objects.get(pk=short_id)
                process_short_video(short_instance, overlay_text)
            except Exception as exc:
                logger.exception("Failed to process short video %s", short_id)
                ShortVideo.objects.filter(pk=short_id).update(
                    status=ShortVideo.STATUS_FAILED,
                    error_message=str(exc) or "Short generation failed.",
                    updated_at=timezone.now(),
                )
            finally:
                close_old_connections()

        Thread(target=_worker, daemon=True).start()


class ShortDetailView(APIView):
    """Fetch metadata for a previously generated short video."""

    def get(self, request, pk: int, *args, **kwargs):
        short = get_object_or_404(ShortVideo, pk=pk)
        serializer = ShortVideoSerializer(short, context={"request": request})
        return Response(serializer.data)


def process_short_video(short: ShortVideo, overlay_text: str) -> None:
    """Download the source video, trim it, add text overlay, and store the resulting short."""
    try:
        from yt_dlp import YoutubeDL
        try:
            from yt_dlp.utils import DownloadError
        except ImportError:
            DownloadError = Exception
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required but not installed. Add it to your environment."
        ) from exc

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
        except ImportError as exc:
            raise RuntimeError(
                "ffmpeg binary not found. Install ffmpeg or add imageio-ffmpeg to the environment."
            ) from exc
        ffmpeg_path = get_ffmpeg_exe()

    if not ffmpeg_path:
        raise RuntimeError("ffmpeg binary not found. Please install ffmpeg.")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Download the YouTube video
        ydl_opts = {
            "outtmpl": str(temp_path / "%(id)s.%(ext)s"),
            "format": "mp4/bestaudio/best",
            "socket_timeout": 10,
            "retries": 2,
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                raw_info = ydl.extract_info(short.youtube_url, download=True)
                if raw_info is None or not isinstance(raw_info, Mapping):
                    raise RuntimeError("Failed to retrieve metadata for the source video.")
                info = cast(dict[str, Any], raw_info)
                downloaded_path = Path(ydl.prepare_filename(info))
        except DownloadError as exc:
            raise RuntimeError(f"Failed to download source video: {exc}") from exc

        # Validate requested start time and duration
        source_duration = info.get("duration")
        if source_duration is not None:
            requested_end = short.start_time + short.duration
            if requested_end > int(source_duration):
                raise ValueError(
                    "Requested start time and duration exceed the source video length."
                )

        # Output path
        trimmed_filename = f"{uuid.uuid4().hex}.mp4"
        trimmed_path = temp_path / trimmed_filename

        # Escape overlay text for FFmpeg
        overlay_text_escaped = overlay_text.replace(":", "\\:").replace("'", "\\'")

        # Text overlay filter
        text_overlay = (
            f"drawtext=text='{overlay_text_escaped}':"
            "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            "fontsize=48:fontcolor=white:"
            "x=(w-text_w)/2:y=50:shadowcolor=black:shadowx=2:shadowy=2"
        )

        # FFmpeg command with a scale-and-crop pipeline to avoid black side bars (full 9:16 fill).
        ffmpeg_command = [
            ffmpeg_path,
            "-y",
            "-ss", str(short.start_time),
            "-i", str(downloaded_path),
            "-t", str(short.duration),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-c:a", "aac",
            "-vf", (
                "scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,"
                "setsar=1,"
                f"{text_overlay}"
            ),
            "-movflags", "+faststart",
            str(trimmed_path),
        ]

        result = subprocess.run(
            ffmpeg_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr}")

        # Save output to media storage
        media_root = Path(settings.MEDIA_ROOT)
        media_root.mkdir(parents=True, exist_ok=True)

        with trimmed_path.open("rb") as trimmed_file:
            short.file.save(trimmed_filename, File(trimmed_file), save=False)

        short.status = ShortVideo.STATUS_COMPLETED
        short.error_message = ""
        short.save(update_fields=["file", "status", "error_message", "updated_at"])


def can_reach_youtube(timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection(("www.youtube.com", 443), timeout=timeout):
            return True
    except OSError:
        return False
