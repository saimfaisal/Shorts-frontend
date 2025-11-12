# cSpell:ignore Roboto Pacifico
from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .models import ShortVideo


OVERLAY_FONT_CHOICES = (
    "Arial",
    "Roboto",
    "Poppins",
    "Pacifico",
    "Montserrat",
)


class ShortGenerationRequestSerializer(serializers.Serializer):
    youtube_url = serializers.URLField()
    duration = serializers.IntegerField(min_value=1)
    start_time = serializers.IntegerField(min_value=0, required=False, default=0)
    overlay_text = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=120,
        trim_whitespace=True,
    )
    overlay_font = serializers.ChoiceField(
        choices=OVERLAY_FONT_CHOICES,
        required=False,
    )
    overlay_color = serializers.RegexField(
        r"^#([0-9A-Fa-f]{6})$",
        required=False,
        allow_blank=False,
    )
    overlay_font_size = serializers.IntegerField(
        min_value=12,
        max_value=200,
        required=False,
    )
    overlay_text_x = serializers.FloatField(min_value=0.0, max_value=1.0, required=False)
    overlay_text_y = serializers.FloatField(min_value=0.0, max_value=1.0, required=False)
    crop_x = serializers.FloatField(min_value=0, required=False)
    crop_y = serializers.FloatField(min_value=0, required=False)
    crop_width = serializers.FloatField(min_value=1, required=False)
    crop_height = serializers.FloatField(min_value=1, required=False)

    def validate(self, attrs):
        crop_fields = ["crop_x", "crop_y", "crop_width", "crop_height"]
        provided = [field in attrs for field in crop_fields]
        if any(provided) and not all(provided):
            raise serializers.ValidationError(
                "Provide all crop_* values when specifying a custom frame."
            )
        return attrs


class ShortPreviewRequestSerializer(serializers.Serializer):
    youtube_url = serializers.URLField()
    start_time = serializers.IntegerField(min_value=0, required=False, default=0)


class ShortVideoSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ShortVideo
        fields = [
            "id",
            "youtube_url",
            "duration",
            "start_time",
            "status",
            "error_message",
            "file",
            "file_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "error_message",
            "file",
            "file_url",
            "created_at",
            "updated_at",
        ]

    def get_file_url(self, obj: ShortVideo) -> str | None:
        if obj.file:
            request: Any = self.context.get("request")
            if request is not None:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None
