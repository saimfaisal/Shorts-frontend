# cSpell:ignore Roboto Pacifico freefont ffprobe FFPROBE
from __future__ import annotations

import base64
import logging
import shutil
import socket
import subprocess
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import Thread
from typing import Any, Optional, TypedDict, cast

from django.conf import settings
from django.core.files import File
from django.db import close_old_connections
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ShortVideo
from .serializers import (
    OVERLAY_FONT_CHOICES,
    ShortGenerationRequestSerializer,
    ShortPreviewRequestSerializer,
    ShortVideoSerializer,
)

logger = logging.getLogger(__name__)

DEFAULT_OVERLAY_TEXT = "My Shorts Video"
DEFAULT_OVERLAY_FONT = "Arial"
DEFAULT_OVERLAY_COLOR = "#FFFFFF"
DEFAULT_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DEFAULT_FONT_SIZE = 48
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_ASPECT = TARGET_WIDTH / TARGET_HEIGHT
FFPROBE_PATH = shutil.which("ffprobe")
FONT_PATH_OVERRIDES = {
    "Arial": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "Roboto": "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    "Poppins": "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "Pacifico": "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "Montserrat": "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
}


def resolve_ffmpeg_path() -> str:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError as exc:  # pragma: no cover - only exercised when ffmpeg missing
        raise RuntimeError(
            "ffmpeg binary not found. Install ffmpeg or add imageio-ffmpeg to the environment."
        ) from exc

    ffmpeg_path = get_ffmpeg_exe()
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg binary not found. Please install ffmpeg.")
    return ffmpeg_path


def resolve_ffprobe_path() -> Optional[str]:
    return FFPROBE_PATH


def _download_source_video(youtube_url: str, temp_path: Path) -> tuple[Path, dict[str, Any]]:
    try:
        from yt_dlp import YoutubeDL
        try:
            from yt_dlp.utils import DownloadError
        except ImportError:  # pragma: no cover - yt_dlp ensures this exists
            DownloadError = Exception
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "yt-dlp is required but not installed. Add it to your environment."
        ) from exc

    ydl_opts = {
        "outtmpl": str(temp_path / "%(id)s.%(ext)s"),
        "format": "mp4/bestaudio/best",
        "socket_timeout": 10,
        "retries": 2,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            raw_info = ydl.extract_info(youtube_url, download=True)
            if raw_info is None or not isinstance(raw_info, Mapping):
                raise RuntimeError("Failed to retrieve metadata for the source video.")
            info = cast(dict[str, Any], raw_info)
            candidate_paths: list[Path] = []

            requested_downloads = info.get("requested_downloads")
            if isinstance(requested_downloads, Sequence):
                for entry in requested_downloads:
                    if isinstance(entry, Mapping):
                        filepath = entry.get("filepath") or entry.get("_filename")
                        if isinstance(filepath, str):
                            candidate_paths.append(Path(filepath))

            for key in ("_filename", "filename", "filepath"):
                value = info.get(key)
                if isinstance(value, str):
                    candidate_paths.append(Path(value))

            try:
                prepared = ydl.prepare_filename(info)
            except KeyError:
                prepared = None
            except OSError as exc:
                raise RuntimeError(f"Failed to download source video: {exc}") from exc
            else:
                candidate_paths.insert(0, Path(prepared))

            seen: set[str] = set()
            resolved_path: Path | None = None
            for candidate in candidate_paths:
                candidate_str = str(candidate)
                if candidate_str in seen:
                    continue
                seen.add(candidate_str)
                candidate_path = candidate
                if not candidate_path.is_absolute():
                    candidate_path = (temp_path / candidate_path).resolve()
                if candidate_path.exists():
                    resolved_path = candidate_path
                    break

            if resolved_path is None:
                fallback_files = [
                    path
                    for path in temp_path.iterdir()
                    if path.is_file()
                    and not path.name.endswith(".part")
                    and not path.name.endswith(".info.json")
                ]
                if fallback_files:
                    fallback_files.sort(key=lambda path: path.stat().st_size, reverse=True)
                    resolved_path = fallback_files[0]

            if resolved_path is None:
                raise RuntimeError(
                    "Downloaded source video was not found. Try again with a different URL."
                )

            downloaded_path = resolved_path
    except DownloadError as exc:
        raise RuntimeError(f"Failed to download source video: {exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"Failed to download source video: {exc}") from exc

    return downloaded_path, info


def _probe_video_dimensions(video_path: Path) -> tuple[Optional[int], Optional[int]]:
    ffprobe_path = resolve_ffprobe_path()
    if not ffprobe_path:
        return None, None

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0",
        str(video_path),
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None, None

    try:
        width_str, height_str = result.stdout.strip().split(",")
        return int(width_str), int(height_str)
    except ValueError:
        return None, None


def _extract_video_dimensions(info: Mapping[str, Any], video_path: Path) -> tuple[int, int]:
    width = info.get("width")
    height = info.get("height")

    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return width, height

    probed_width, probed_height = _probe_video_dimensions(video_path)
    if (
        isinstance(probed_width, int)
        and isinstance(probed_height, int)
        and probed_width > 0
        and probed_height > 0
    ):
        return probed_width, probed_height

    raise RuntimeError("Unable to determine source video dimensions.")


def _normalize_crop_area(
    crop: CropOptions, source_width: int, source_height: int
) -> CropOptions | None:
    """Clamp the user selection to the source bounds and quantize to even integers."""
    x = max(0.0, min(float(crop["x"]), float(source_width - 1)))
    y = max(0.0, min(float(crop["y"]), float(source_height - 1)))
    width = max(1.0, float(crop["width"]))
    height = max(1.0, float(crop["height"]))

    if x + width > source_width:
        width = max(1.0, source_width - x)
    if y + height > source_height:
        height = max(1.0, source_height - y)

    if width <= 1 or height <= 1:
        return None

    left = int(round(x))
    top = int(round(y))
    right = min(source_width, int(round(x + width)))
    bottom = min(source_height, int(round(y + height)))

    width_int = max(2, right - left)
    height_int = max(2, bottom - top)

    if width_int % 2:
        width_int -= 1
    if height_int % 2:
        height_int -= 1

    if width_int < 2 or height_int < 2:
        return None

    if left + width_int > source_width:
        left = max(0, source_width - width_int)
    if top + height_int > source_height:
        top = max(0, source_height - height_int)

    return {
        "x": float(left),
        "y": float(top),
        "width": float(width_int),
        "height": float(height_int),
    }


class _ShortGenerationPayloadRequired(TypedDict):
    youtube_url: str
    duration: int


class _ShortGenerationPayload(_ShortGenerationPayloadRequired, total=False):
    start_time: int
    overlay_text: str
    overlay_font: str
    overlay_color: str
    overlay_font_size: int
    overlay_text_x: float
    overlay_text_y: float
    crop_x: float
    crop_y: float
    crop_width: float
    crop_height: float


class OverlayOptionsRequired(TypedDict):
    text: str
    font: str
    color: str
    font_size: int


class OverlayOptions(OverlayOptionsRequired, total=False):
    position_x_ratio: float
    position_y_ratio: float


class CropOptions(TypedDict):
    x: float
    y: float
    width: float
    height: float


class _ShortPreviewPayloadRequired(TypedDict):
    youtube_url: str


class _ShortPreviewPayload(_ShortPreviewPayloadRequired, total=False):
    start_time: int


class _CropPayload(TypedDict):
    crop_x: float
    crop_y: float
    crop_width: float
    crop_height: float


class ShortGenerateView(APIView):
    """Handle creation of short videos from YouTube sources."""

    def post(self, request, *args, **kwargs):
        request_serializer = ShortGenerationRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload: _ShortGenerationPayload = cast(
            _ShortGenerationPayload,
            request_serializer.validated_data,
        )

        if not can_reach_youtube():
            return Response(
                {"message": "Unable to reach YouTube. Check your internet connection and try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        youtube_url = payload["youtube_url"]
        duration = payload["duration"]
        start_time = payload.get("start_time", 0)
        overlay_text = (payload.get("overlay_text") or "").strip() or DEFAULT_OVERLAY_TEXT
        overlay_font = payload.get("overlay_font") or DEFAULT_OVERLAY_FONT
        if overlay_font not in OVERLAY_FONT_CHOICES:
            overlay_font = DEFAULT_OVERLAY_FONT
        raw_color = payload.get("overlay_color") or DEFAULT_OVERLAY_COLOR
        overlay_color = raw_color.upper() if raw_color.startswith("#") else f"#{raw_color.upper()}"
        if len(overlay_color) != 7:
            overlay_color = DEFAULT_OVERLAY_COLOR
        raw_font_size = payload.get("overlay_font_size")
        try:
            overlay_font_size = int(raw_font_size) if raw_font_size is not None else DEFAULT_FONT_SIZE
        except (TypeError, ValueError):
            overlay_font_size = DEFAULT_FONT_SIZE
        if overlay_font_size <= 0:
            overlay_font_size = DEFAULT_FONT_SIZE
        text_x_ratio = payload.get("overlay_text_x")
        text_y_ratio = payload.get("overlay_text_y")
        position_x_ratio = float(text_x_ratio) if text_x_ratio is not None else None
        position_y_ratio = float(text_y_ratio) if text_y_ratio is not None else None
        if position_x_ratio is not None:
            position_x_ratio = max(0.0, min(1.0, position_x_ratio))
        if position_y_ratio is not None:
            position_y_ratio = max(0.0, min(1.0, position_y_ratio))

        overlay_options: OverlayOptions = {
            "text": overlay_text,
            "font": overlay_font,
            "color": overlay_color,
            "font_size": overlay_font_size,
        }
        if position_x_ratio is not None:
            overlay_options["position_x_ratio"] = position_x_ratio
        if position_y_ratio is not None:
            overlay_options["position_y_ratio"] = position_y_ratio

        crop_options: CropOptions | None = None
        crop_fields = ("crop_x", "crop_y", "crop_width", "crop_height")
        if all(field in payload for field in crop_fields):
            crop_payload = cast(_CropPayload, payload)
            crop_options = {
                "x": float(crop_payload["crop_x"]),
                "y": float(crop_payload["crop_y"]),
                "width": float(crop_payload["crop_width"]),
                "height": float(crop_payload["crop_height"]),
            }

        short = ShortVideo.objects.create(
            youtube_url=youtube_url,
            duration=duration,
            start_time=start_time,
            status=ShortVideo.STATUS_PROCESSING,
        )
        self._start_background_processing(short.pk, overlay_options, crop_options)

        response_serializer = ShortVideoSerializer(short, context={"request": request})
        return Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)

    @staticmethod
    def _start_background_processing(
        short_id: int,
        overlay_options: OverlayOptions,
        crop_options: CropOptions | None,
    ) -> None:
        def _worker() -> None:
            close_old_connections()
            try:
                short_instance = ShortVideo.objects.get(pk=short_id)
                process_short_video(short_instance, overlay_options, crop_options)
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


class ShortPreviewView(APIView):
    """Provide a still frame preview so the frontend can capture crop coordinates."""

    def post(self, request, *args, **kwargs):
        serializer = ShortPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload: _ShortPreviewPayload = cast(
            _ShortPreviewPayload,
            serializer.validated_data,
        )

        if not can_reach_youtube():
            return Response(
                {"message": "Unable to reach YouTube. Check your internet connection and try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            preview = generate_preview_frame(
                youtube_url=payload["youtube_url"],
                start_time=payload.get("start_time", 0),
            )
        except RuntimeError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(preview, status=status.HTTP_200_OK)


def _escape_drawtext_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


def generate_preview_frame(youtube_url: str, start_time: int) -> dict[str, Any]:
    ffmpeg_path = resolve_ffmpeg_path()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        downloaded_path, info = _download_source_video(youtube_url, temp_path)
        source_width, source_height = _extract_video_dimensions(info, downloaded_path)

        frame_path = temp_path / "preview.jpg"
        command = [
            ffmpeg_path,
            "-y",
            "-ss",
            str(max(0, start_time)),
            "-i",
            str(downloaded_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame_path),
        ]
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not frame_path.exists():
            raise RuntimeError("Failed to capture preview frame from the source video.")

        image_bytes = frame_path.read_bytes()
        encoded = base64.b64encode(image_bytes).decode("ascii")

    return {
        "image": f"data:image/jpeg;base64,{encoded}",
        "width": source_width,
        "height": source_height,
    }


def process_short_video(
    short: ShortVideo,
    overlay: OverlayOptions,
    crop: CropOptions | None,
) -> None:
    """Download the source video, trim it, add text overlay, and store the resulting short."""
    ffmpeg_path = resolve_ffmpeg_path()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        downloaded_path, info = _download_source_video(short.youtube_url, temp_path)
        source_width, source_height = _extract_video_dimensions(info, downloaded_path)

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

        crop_filter = ""
        use_custom_crop = False
        if crop is not None:
            normalized = _normalize_crop_area(crop, source_width, source_height)
            if normalized is not None:
                crop_w = max(2, int(round(normalized["width"])))
                crop_h = max(2, int(round(normalized["height"])))
                crop_x = max(0, int(round(normalized["x"])))
                crop_y = max(0, int(round(normalized["y"])))
                crop_filter = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}"
                use_custom_crop = True

        # Escape overlay text for FFmpeg
        overlay_text_escaped = _escape_drawtext_value(overlay["text"])
        color_value = overlay["color"].lstrip("#")
        if len(color_value) != 6:
            color_value = "FFFFFF"
        fontcolor_value = f"0x{color_value.upper()}"

        requested_font = overlay.get("font") or "Arial"
        font_path = FONT_PATH_OVERRIDES.get(requested_font, DEFAULT_FONT_PATH)
        if not Path(font_path).exists():
            font_path = DEFAULT_FONT_PATH

        font_size = overlay.get("font_size", DEFAULT_FONT_SIZE)
        try:
            font_size_value = int(font_size)
        except (TypeError, ValueError):
            font_size_value = DEFAULT_FONT_SIZE
        if font_size_value <= 0:
            font_size_value = DEFAULT_FONT_SIZE

        position_x_ratio = overlay.get("position_x_ratio")
        position_y_ratio = overlay.get("position_y_ratio")

        if position_x_ratio is not None:
            x_ratio_str = f"{float(position_x_ratio):.6f}"
            x_expression = (
                f"min(max(w*{x_ratio_str}-text_w/2\\,0)\\,w-text_w)"
            )
        else:
            x_expression = "(w-text_w)/2"

        if position_y_ratio is not None:
            y_ratio_str = f"{float(position_y_ratio):.6f}"
            y_expression = (
                f"min(max(h*{y_ratio_str}-text_h/2\\,0)\\,h-text_h)"
            )
        else:
            y_expression = "50"

        filters: list[str] = []
        if use_custom_crop and crop_filter:
            filters.append(crop_filter)
            filters.append("scale=1080:1920:force_original_aspect_ratio=decrease")
            filters.append("pad=1080:1920:(1080-iw)/2:(1920-ih)/2")
            filters.append("setsar=1")
        else:
            filters.extend(
                [
                    "scale=1080:1920:force_original_aspect_ratio=increase",
                    "crop=1080:1920",
                    "setsar=1",
                ]
            )

        # Text overlay filter
        text_overlay = (
            f"drawtext=text='{overlay_text_escaped}':"
            f"fontfile={font_path}:"
            f"fontsize={font_size_value}:"
            f"fontcolor={fontcolor_value}:"
            f"x={x_expression}:"
            f"y={y_expression}:"
            "shadowcolor=black:shadowx=2:shadowy=2"
        )
        filters.append(text_overlay)
        video_filters = ",".join(filters)

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
                video_filters
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
