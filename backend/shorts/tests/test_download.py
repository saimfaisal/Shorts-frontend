from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

from django.test import SimpleTestCase

from shorts import views


class DownloadSourceVideoTests(SimpleTestCase):
    def test_falls_back_to_requested_downloads_when_prepare_filename_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fallback_file = temp_path / "sample.webm"
            fallback_file.write_bytes(b"not real video data")

            info: dict[str, Any] = {
                "id": "abc123",
                "requested_downloads": [
                    {"filepath": str(fallback_file)},
                ],
            }

            class DummyDL:
                def __init__(self, opts: dict[str, Any]) -> None:
                    self.opts = opts

                def __enter__(self) -> "DummyDL":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:
                    return False

                def extract_info(self, url: str, download: bool) -> dict[str, Any]:
                    return info

                def prepare_filename(self, info_dict: dict[str, Any]) -> str:
                    raise KeyError("ext")

            with mock.patch("yt_dlp.YoutubeDL", DummyDL):
                downloaded_path, returned_info = views._download_source_video(
                    "https://example.com/watch?v=dummy",
                    temp_path,
                )

        self.assertEqual(downloaded_path, fallback_file.resolve())
        self.assertEqual(returned_info, info)
