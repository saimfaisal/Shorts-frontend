// cSpell:ignore Roboto Pacifico Montserrat youtu
import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FrameCropper } from "./FrameCropper";
import { fetchShortPreview } from "../lib/api";

const FONT_OPTIONS = [
  { label: "Arial", value: "Arial" },
  { label: "Roboto", value: "Roboto" },
  { label: "Poppins", value: "Poppins" },
  { label: "Pacifico", value: "Pacifico" },
  { label: "Montserrat", value: "Montserrat" }
];

const initialState = {
  youtubeUrl: "",
  duration: "30",
  startTime: "",
  overlayText: "My Shorts Video",
  overlayFont: FONT_OPTIONS[0].value,
  overlayColor: "#ffffff",
  overlayFontSize: "48"
};

const colonTimePattern = /^(\d{1,2}:){0,2}\d{1,2}$/;

const parseStartTime = (value) => {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }

  if (/^\d+$/.test(trimmed)) {
    return Number(trimmed);
  }

  if (!colonTimePattern.test(trimmed)) {
    return undefined;
  }

  const segments = trimmed.split(":").map(Number);
  if (segments.some((segment) => Number.isNaN(segment))) {
    return undefined;
  }

  return segments.reduceRight((acc, segment, index, array) => {
    const power = array.length - 1 - index;
    return acc + segment * 60 ** power;
  }, 0);
};

const isLikelyYoutubeUrl = (value) => {
  if (!value.trim()) {
    return false;
  }

  try {
    const parsed = new URL(value);
    return /youtube\.com|youtu\.be/.test(parsed.hostname);
  } catch {
    return /youtube\.com|youtu\.be/.test(value);
  }
};

const overlayColorPattern = /^#([0-9a-fA-F]{6})$/;

const fontPreviewFamilies = {
  Arial: `"Arial", "Helvetica Neue", Helvetica, sans-serif`,
  Roboto: `"Roboto", "Helvetica Neue", Helvetica, sans-serif`,
  Poppins: `"Poppins", "Helvetica Neue", Helvetica, sans-serif`,
  Pacifico: `"Pacifico", cursive`,
  Montserrat: `"Montserrat", "Helvetica Neue", Helvetica, sans-serif`
};

const MIN_FONT_SIZE = 20;
const MAX_FONT_SIZE = 100;
const DEFAULT_FONT_SIZE = 48;
const DEFAULT_TEXT_POSITION = { x: 0.5, y: 50 / 1920 };

const getPreviewErrorMessage = (error) => {
  if (axios.isAxiosError(error)) {
    const message = error.response?.data?.message;
    if (typeof message === "string" && message.trim().length > 0) {
      return message;
    }

    if (error.response?.status) {
      return `Preview request failed with status ${error.response.status}.`;
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Unable to load a preview frame. Please try again.";
};

export const ShortsForm = ({ onSubmit, isLoading, onResetResult }) => {
  const [values, setValues] = useState(initialState);
  const [errors, setErrors] = useState({});
  const [preview, setPreview] = useState(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [cropSelection, setCropSelection] = useState(null);
  const [overlayPosition, setOverlayPosition] = useState(DEFAULT_TEXT_POSITION);
  const [isDraggingText, setIsDraggingText] = useState(false);
  const overlayContainerRef = useRef(null);
  const overlayTextRef = useRef(null);
  const initializedPositionRef = useRef(false);

  const isPristine = useMemo(
    () =>
      values.youtubeUrl === initialState.youtubeUrl &&
      values.duration === initialState.duration &&
      values.startTime === initialState.startTime &&
      values.overlayText === initialState.overlayText &&
      values.overlayFont === initialState.overlayFont &&
      values.overlayColor === initialState.overlayColor &&
      values.overlayFontSize === initialState.overlayFontSize &&
      !preview &&
      !cropSelection,
    [values, preview, cropSelection]
  );

  const handleChange =
    (field) =>
    (event) => {
      setValues((prev) => ({
        ...prev,
        [field]: event.target.value
      }));

      if (errors[field]) {
        setErrors((prev) => {
          const next = { ...prev };
          delete next[field];
          return next;
        });
      }

      if (field === "youtubeUrl" || field === "startTime") {
        setPreview(null);
        setCropSelection(null);
        setPreviewError(null);
      }

      if (field === "youtubeUrl" && onResetResult) {
        onResetResult();
      }
    };

  const handleLoadPreview = useCallback(async () => {
    const trimmedUrl = values.youtubeUrl.trim();
    const nextErrors = {};

    if (!trimmedUrl) {
      nextErrors.youtubeUrl = "Paste a YouTube video link to continue.";
    } else if (!isLikelyYoutubeUrl(trimmedUrl)) {
      nextErrors.youtubeUrl = "Enter a valid YouTube URL.";
    }

    const parsedStartTime = parseStartTime(values.startTime);
    if (values.startTime && parsedStartTime === undefined) {
      nextErrors.startTime = "Use seconds (e.g. 45) or HH:MM:SS format.";
    }

    if (Object.keys(nextErrors).length > 0) {
      setErrors((prev) => ({ ...prev, ...nextErrors }));
      return;
    }

    setIsPreviewLoading(true);
    setPreviewError(null);

    try {
      const payload = {
        youtube_url: trimmedUrl
      };

      if (parsedStartTime !== undefined) {
        payload.start_time = parsedStartTime;
      }

      const response = await fetchShortPreview(payload);
      setPreview(response);
      setCropSelection(null);
      setOverlayPosition(DEFAULT_TEXT_POSITION);
      initializedPositionRef.current = false;
      setErrors((prev) => {
        const next = { ...prev };
        delete next.youtubeUrl;
        delete next.startTime;
        return next;
      });
    } catch (error) {
      setPreviewError(getPreviewErrorMessage(error));
    } finally {
      setIsPreviewLoading(false);
    }
  }, [values.youtubeUrl, values.startTime]);

  const handleClearCrop = useCallback(() => {
    setCropSelection(null);
  }, []);

  const updateOverlayPosition = useCallback((clientX, clientY) => {
    if (!overlayContainerRef.current) {
      return;
    }

    const containerRect = overlayContainerRef.current.getBoundingClientRect();
    if (containerRect.width === 0 || containerRect.height === 0) {
      return;
    }

    const textRect = overlayTextRef.current?.getBoundingClientRect();
    const halfWidth = (textRect?.width ?? 0) / 2;
    const halfHeight = (textRect?.height ?? 0) / 2;

    const boundedX = Math.max(
      halfWidth,
      Math.min(clientX - containerRect.left, containerRect.width - halfWidth)
    );
    const boundedY = Math.max(
      halfHeight,
      Math.min(clientY - containerRect.top, containerRect.height - halfHeight)
    );

    setOverlayPosition({
      x: containerRect.width ? boundedX / containerRect.width : DEFAULT_TEXT_POSITION.x,
      y: containerRect.height ? boundedY / containerRect.height : DEFAULT_TEXT_POSITION.y
    });
  }, []);

  const handleTextPointerDown = useCallback(
    (event) => {
      setIsDraggingText(true);
      updateOverlayPosition(event.clientX, event.clientY);
      event.currentTarget.setPointerCapture(event.pointerId);
      event.preventDefault();
    },
    [updateOverlayPosition]
  );

  const handleTextPointerMove = useCallback(
    (event) => {
      if (!isDraggingText) {
        return;
      }
      updateOverlayPosition(event.clientX, event.clientY);
    },
    [isDraggingText, updateOverlayPosition]
  );

  const stopDragging = useCallback(
    (event) => {
      if (isDraggingText) {
        setIsDraggingText(false);
        try {
          event.currentTarget.releasePointerCapture(event.pointerId);
        } catch (err) {
          // Ignore if pointer capture was already released.
        }
      }
    },
    [isDraggingText]
  );

  useEffect(() => {
    if (initializedPositionRef.current) {
      return;
    }

    if (!overlayContainerRef.current || !overlayTextRef.current) {
      return;
    }

    const containerRect = overlayContainerRef.current.getBoundingClientRect();
    const textRect = overlayTextRef.current.getBoundingClientRect();
    if (containerRect.width === 0 || containerRect.height === 0) {
      return;
    }

    const minY = (DEFAULT_TEXT_POSITION.y || 0) * containerRect.height;
    const centerX = (containerRect.width - textRect.width) / 2 + textRect.width / 2;
    const centerY = Math.max(textRect.height / 2, minY + textRect.height / 2);

    setOverlayPosition({
      x: containerRect.width ? centerX / containerRect.width : DEFAULT_TEXT_POSITION.x,
      y: containerRect.height ? centerY / containerRect.height : DEFAULT_TEXT_POSITION.y
    });
    initializedPositionRef.current = true;
  }, [values.overlayText, values.overlayFont, values.overlayFontSize, preview]);

  const validate = () => {
    const nextErrors = {};

    if (!values.youtubeUrl.trim()) {
      nextErrors.youtubeUrl = "Paste a YouTube video link to continue.";
    } else if (!isLikelyYoutubeUrl(values.youtubeUrl.trim())) {
      nextErrors.youtubeUrl = "Enter a valid YouTube URL.";
    }

    const durationNumber = Number(values.duration);
    if (!values.duration.trim()) {
      nextErrors.duration = "Duration is required.";
    } else if (Number.isNaN(durationNumber) || durationNumber <= 0) {
      nextErrors.duration = "Use a positive number of seconds.";
    }

    const parsedStartTime = parseStartTime(values.startTime);
    if (values.startTime && parsedStartTime === undefined) {
      nextErrors.startTime = "Use seconds (e.g. 45) or HH:MM:SS format.";
    }

    if (values.overlayColor && !overlayColorPattern.test(values.overlayColor)) {
      nextErrors.overlayColor = "Pick a valid hex color.";
    }

    const parsedFontSize = Number(values.overlayFontSize);
    if (!values.overlayFontSize.toString().trim()) {
      nextErrors.overlayFontSize = "Choose a font size.";
    } else if (
      Number.isNaN(parsedFontSize) ||
      parsedFontSize < MIN_FONT_SIZE ||
      parsedFontSize > MAX_FONT_SIZE
    ) {
      nextErrors.overlayFontSize = `Use a size between ${MIN_FONT_SIZE} and ${MAX_FONT_SIZE}.`;
    }

    setErrors(nextErrors);

    if (Object.keys(nextErrors).length > 0) {
      return { success: false };
    }

    const payload = {
      youtube_url: values.youtubeUrl.trim(),
      duration: Math.round(durationNumber)
    };

    if (parsedStartTime !== undefined) {
      payload.start_time = parsedStartTime;
    }

    const overlayText = values.overlayText.trim();
    if (overlayText) {
      payload.overlay_text = overlayText;
    }

    if (values.overlayFont) {
      payload.overlay_font = values.overlayFont;
    }

    if (values.overlayColor && overlayColorPattern.test(values.overlayColor)) {
      payload.overlay_color = values.overlayColor;
    }

    if (!Number.isNaN(parsedFontSize)) {
      payload.overlay_font_size = Math.round(parsedFontSize);
    }

    if (overlayPosition) {
      payload.overlay_text_x = Number(overlayPosition.x.toFixed(4));
      payload.overlay_text_y = Number(overlayPosition.y.toFixed(4));
    }

    if (cropSelection) {
      payload.crop_x = Math.round(cropSelection.x);
      payload.crop_y = Math.round(cropSelection.y);
      payload.crop_width = Math.round(cropSelection.width);
      payload.crop_height = Math.round(cropSelection.height);
    }

    return { success: true, payload };
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const { success, payload } = validate();

    if (!success || !payload) {
      return;
    }

    await onSubmit(payload);
  };

  const handleReset = () => {
    setValues(initialState);
    setErrors({});
    setPreview(null);
    setCropSelection(null);
    setPreviewError(null);
    setIsPreviewLoading(false);
    setOverlayPosition(DEFAULT_TEXT_POSITION);
    setIsDraggingText(false);
    initializedPositionRef.current = false;
    onResetResult?.();
  };

  const previewText = values.overlayText.trim() || "My Shorts Video";
  const previewFontFamily =
    fontPreviewFamilies[values.overlayFont] ?? fontPreviewFamilies.Arial;

  return (
    <form onSubmit={handleSubmit} className="space-y-6" noValidate>
      <div className="space-y-2">
        <label htmlFor="youtubeUrl" className="text-sm font-medium text-slate-700">
          YouTube Video URL
        </label>
        <input
          id="youtubeUrl"
          name="youtubeUrl"
          type="url"
          placeholder="https://www.youtube.com/watch?v=..."
          value={values.youtubeUrl}
          onChange={handleChange("youtubeUrl")}
          className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-black placeholder:text-slate-400 shadow-sm transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
          autoComplete="off"
          required
        />
        {errors.youtubeUrl && (
          <p className="text-sm text-rose-400" role="alert">
            {errors.youtubeUrl}
          </p>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr,minmax(12rem,18rem)]">
        <div className="space-y-6">
          <div className="space-y-2">
            <label htmlFor="overlayText" className="text-sm font-medium text-slate-700">
              Overlay Text
            </label>
            <input
              id="overlayText"
              name="overlayText"
              type="text"
              placeholder="My Short Video"
              value={values.overlayText}
              onChange={handleChange("overlayText")}
              className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-black placeholder:text-slate-400 shadow-sm transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
            />
            <p className="text-sm text-slate-500">
              Leave blank to use the default title when generating the video.
            </p>
          </div>

          <div className="grid gap-6 sm:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="overlayFont" className="text-sm font-medium text-slate-700">
                Font
              </label>
              <select
                id="overlayFont"
                name="overlayFont"
                value={values.overlayFont}
                onChange={handleChange("overlayFont")}
                className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-black shadow-sm transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
              >
                {FONT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <label htmlFor="overlayColor" className="text-sm font-medium text-slate-700">
                Text Color
              </label>
              <input
                id="overlayColor"
                name="overlayColor"
                type="color"
                value={values.overlayColor}
                onChange={handleChange("overlayColor")}
                className="h-12 w-full cursor-pointer rounded-lg border border-slate-200 bg-white shadow-sm transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
              />
              {errors.overlayColor ? (
                <p className="text-sm text-rose-400" role="alert">
                  {errors.overlayColor}
                </p>
              ) : (
                <p className="text-sm text-slate-500">Choose any color for the overlay text.</p>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <label htmlFor="overlayFontSize" className="text-sm font-medium text-slate-700">
              Text Size
            </label>
            <div className="flex items-center gap-3">
              <input
                id="overlayFontSize"
                name="overlayFontSize"
                type="range"
                min={MIN_FONT_SIZE}
                max={MAX_FONT_SIZE}
                value={values.overlayFontSize}
                onChange={handleChange("overlayFontSize")}
                className="flex-1 accent-brand"
              />
              <input
                type="number"
                min={MIN_FONT_SIZE}
                max={MAX_FONT_SIZE}
                value={values.overlayFontSize}
                onChange={handleChange("overlayFontSize")}
                className="w-20 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-black shadow-sm transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
              />
            </div>
            {errors.overlayFontSize ? (
              <p className="text-sm text-rose-400" role="alert">
                {errors.overlayFontSize}
              </p>
            ) : (
              <p className="text-sm text-slate-500">
                Drag the overlay text on the preview to position it anywhere.
              </p>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-slate-900/60 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs uppercase tracking-wide text-slate-200">Frame Preview</p>
              <button
                type="button"
                onClick={handleLoadPreview}
                className="inline-flex items-center rounded-md border border-emerald-400/60 px-3 py-1.5 text-xs font-semibold text-emerald-200 transition hover:border-emerald-300 hover:text-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isPreviewLoading || !values.youtubeUrl.trim()}
              >
                {isPreviewLoading
                  ? "Loading…"
                  : preview
                  ? "Refresh Preview"
                  : "Load Preview"}
              </button>
            </div>
            <p className="mt-2 text-xs text-slate-300">
              Choose the focal region you want to keep in focus. Skip this step to let us auto-center
              the short.
            </p>

            <div className="mt-4">
              {preview ? (
                <>
                  <FrameCropper
                    src={preview.image}
                    naturalWidth={preview.width}
                    naturalHeight={preview.height}
                    value={cropSelection}
                    onChange={setCropSelection}
                  />
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-200/80">
                    <span>
                      Source frame: {preview.width}×{preview.height}px
                    </span>
                    {cropSelection ? (
                      <button
                        type="button"
                        onClick={handleClearCrop}
                        className="rounded px-2 py-1 text-emerald-200 underline-offset-2 transition hover:text-emerald-100 hover:underline"
                      >
                        Clear selection
                      </button>
                    ) : (
                      <span className="text-slate-400">Selection optional</span>
                    )}
                  </div>
                  <p className="mt-2 text-xs text-slate-400">
                    The generator adjusts your selection to fit a vertical 9:16 canvas.
                  </p>
                </>
              ) : isPreviewLoading ? (
                <div className="flex min-h-[180px] items-center justify-center rounded-xl border border-dashed border-slate-700 bg-slate-800/40 text-sm text-slate-200">
                  Fetching preview frame…
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-slate-700 bg-slate-800/40 p-4 text-sm text-slate-300">
                  Load a preview frame to drag and highlight the subject you want centered in the final
                  short.
                </div>
              )}
            </div>

            {previewError && (
              <p className="mt-3 text-sm text-rose-300" role="alert">
                {previewError}
              </p>
            )}
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-900/60 p-4">
            <p className="text-xs uppercase tracking-wide text-slate-200">Overlay Preview</p>
            <div className="mt-3 flex justify-center">
              <div
                ref={overlayContainerRef}
                className="relative aspect-[9/16] w-full max-w-[200px] overflow-hidden rounded-xl border border-slate-700 bg-gradient-to-br from-slate-800 via-slate-900 to-slate-950 shadow-inner"
              >
                <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.4),_transparent_55%)]" />
                <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_bottom,_rgba(234,179,8,0.25),_transparent_50%)]" />
                <div
                  ref={overlayTextRef}
                  className="absolute cursor-move select-none rounded bg-slate-950/40 px-3 py-1 text-center font-semibold tracking-wide shadow-lg shadow-black/40"
                  style={{
                    color: values.overlayColor,
                    fontFamily: previewFontFamily,
                    fontSize: `${Number(values.overlayFontSize) || DEFAULT_FONT_SIZE}px`,
                    left: `${overlayPosition.x * 100}%`,
                    top: `${overlayPosition.y * 100}%`,
                    transform: "translate(-50%, -50%)"
                  }}
                  onPointerDown={handleTextPointerDown}
                  onPointerMove={handleTextPointerMove}
                  onPointerUp={stopDragging}
                  onPointerCancel={stopDragging}
                >
                  {previewText}
                </div>
                <div className="absolute bottom-4 left-1/2 h-12 w-12 -translate-x-1/2 rounded-full border border-slate-700 bg-slate-800/80 shadow-lg shadow-black/50" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        <div className="space-y-2">
          <label htmlFor="duration" className="text-sm font-medium text-slate-700">
            Short Duration (seconds)
          </label>
          <input
            id="duration"
            name="duration"
            type="number"
            min={1}
            placeholder="15"
            value={values.duration}
            onChange={handleChange("duration")}
            className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-black placeholder:text-slate-400 shadow-sm transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
            required
          />
          {errors.duration && (
            <p className="text-sm text-rose-400" role="alert">
              {errors.duration}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <label htmlFor="startTime" className="text-sm font-medium text-slate-700">
            Start Time (optional)
          </label>
          <input
            id="startTime"
            name="startTime"
            type="text"
            placeholder="e.g. 1:20 or 80"
            value={values.startTime}
            onChange={handleChange("startTime")}
            className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-black placeholder:text-slate-400 shadow-sm transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
          />
          {errors.startTime ? (
            <p className="text-sm text-rose-400" role="alert">
              {errors.startTime}
            </p>
          ) : (
            <p className="text-sm text-slate-500">Use seconds or HH:MM:SS.</p>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="submit"
          className="inline-flex w-full items-center justify-center rounded-lg bg-brand px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-brand/30 transition hover:bg-brand-dark focus:outline-none focus:ring-2 focus:ring-brand/40 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500 sm:w-auto"
          disabled={Boolean(isLoading)}
        >
          {isLoading ? "Generating…" : "Generate Short"}
        </button>
        <button
          type="button"
          onClick={handleReset}
          className="inline-flex w-full items-center justify-center rounded-lg bg-black px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500 sm:w-auto"
          disabled={isLoading || isPristine}
        >
          Reset
        </button>
      </div>
    </form>
  );
};
