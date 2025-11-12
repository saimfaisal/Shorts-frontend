import { useCallback, useEffect, useRef, useState } from "react";

const MIN_SELECTION_PIXELS = 12;

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

const computeRect = (start, end) => {
  const left = Math.min(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const width = Math.abs(end.x - start.x);
  const height = Math.abs(end.y - start.y);
  return { left, top, width, height };
};

export const FrameCropper = ({
  src,
  naturalWidth,
  naturalHeight,
  value,
  onChange
}) => {
  const containerRef = useRef(null);
  const imageRef = useRef(null);
  const [dragState, setDragState] = useState(null);
  const [displaySize, setDisplaySize] = useState({ width: 0, height: 0 });

  const updateDisplaySize = useCallback(() => {
    if (!imageRef.current) {
      return;
    }
    setDisplaySize({
      width: imageRef.current.clientWidth,
      height: imageRef.current.clientHeight
    });
  }, []);

  useEffect(() => {
    updateDisplaySize();
  }, [src, updateDisplaySize]);

  useEffect(() => {
    const handleResize = () => {
      updateDisplaySize();
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [updateDisplaySize]);

  const projectPoint = useCallback((event, rect) => {
    const x = clamp(event.clientX - rect.left, 0, rect.width);
    const y = clamp(event.clientY - rect.top, 0, rect.height);
    return { x, y };
  }, []);

  const handlePointerDown = useCallback(
    (event) => {
      if (!imageRef.current || !naturalWidth || !naturalHeight) {
        return;
      }

      const rect = imageRef.current.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) {
        return;
      }

      const point = projectPoint(event, rect);
      setDragState({
        rect,
        origin: point,
        current: point
      });
      event.currentTarget.setPointerCapture(event.pointerId);
      event.preventDefault();
    },
    [naturalHeight, naturalWidth, projectPoint]
  );

  const handlePointerMove = useCallback(
    (event) => {
      setDragState((prev) => {
        if (!prev) {
          return prev;
        }
        const point = projectPoint(event, prev.rect);
        return {
          ...prev,
          current: point
        };
      });
    },
    [projectPoint]
  );

  const finalizeSelection = useCallback(
    (state) => {
      if (!state || !naturalWidth || !naturalHeight) {
        return;
      }
      const { rect, origin, current } = state;
      const draftRect = computeRect(origin, current);

      if (
        draftRect.width < MIN_SELECTION_PIXELS ||
        draftRect.height < MIN_SELECTION_PIXELS
      ) {
        onChange?.(null);
        return;
      }

      const scaleX = naturalWidth / rect.width;
      const scaleY = naturalHeight / rect.height;
      const selection = {
        x: Math.round(draftRect.left * scaleX),
        y: Math.round(draftRect.top * scaleY),
        width: Math.round(draftRect.width * scaleX),
        height: Math.round(draftRect.height * scaleY)
      };

      onChange?.(selection);
    },
    [naturalHeight, naturalWidth, onChange]
  );

  const handlePointerUp = useCallback(
    (event) => {
      event.currentTarget.releasePointerCapture(event.pointerId);
      setDragState((prev) => {
        if (prev) {
          finalizeSelection(prev);
        }
        return null;
      });
    },
    [finalizeSelection]
  );

  const handlePointerCancel = useCallback(() => {
    setDragState(null);
  }, []);

  const activeRect = (() => {
    const current = dragState
      ? computeRect(dragState.origin, dragState.current)
      : null;
    if (current) {
      return current;
    }

    if (
      value &&
      naturalWidth &&
      naturalHeight &&
      displaySize.width > 0 &&
      displaySize.height > 0
    ) {
      return {
        left: (value.x / naturalWidth) * displaySize.width,
        top: (value.y / naturalHeight) * displaySize.height,
        width: (value.width / naturalWidth) * displaySize.width,
        height: (value.height / naturalHeight) * displaySize.height
      };
    }

    return null;
  })();

  return (
    <div
      ref={containerRef}
      className="relative w-full select-none overflow-hidden rounded-xl border border-slate-200 bg-black/80"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={dragState ? handlePointerCancel : undefined}
      onPointerCancel={handlePointerCancel}
      role="presentation"
    >
      <img
        ref={imageRef}
        src={src}
        alt="Video preview frame"
        className="block h-auto w-full"
        onLoad={updateDisplaySize}
        draggable={false}
      />

      {activeRect && (
        <div
          className="pointer-events-none absolute border-2 border-emerald-400/90 bg-emerald-400/10 shadow-[0_0_0_5000px_rgba(15,23,42,0.55)]"
          style={{
            left: `${activeRect.left}px`,
            top: `${activeRect.top}px`,
            width: `${activeRect.width}px`,
            height: `${activeRect.height}px`
          }}
        />
      )}

      <div className="pointer-events-none absolute inset-0 flex items-end justify-between p-3 text-xs text-white/80">
        <span>Click and drag to choose the focal area.</span>
        {value ? (
          <span>
            {Math.round(value.width)}×{Math.round(value.height)} px
          </span>
        ) : (
          <span>Selection optional</span>
        )}
      </div>
    </div>
  );
};
