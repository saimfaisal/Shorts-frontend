export type ShortStatus = "pending" | "processing" | "completed" | "failed";

export interface ShortGenerationPayload {
  youtube_url: string;
  duration: number;
  start_time?: number;
  overlay_text?: string;
  overlay_font?: string;
  overlay_color?: string;
  overlay_font_size?: number;
  overlay_text_x?: number;
  overlay_text_y?: number;
  crop_x?: number;
  crop_y?: number;
  crop_width?: number;
  crop_height?: number;
}

export interface ShortVideo {
  id: number;
  youtube_url: string;
  duration: number;
  start_time: number;
  status: ShortStatus;
  error_message: string;
  file: string | null;
  file_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ShortPreviewPayload {
  youtube_url: string;
  start_time?: number;
}

export interface ShortPreviewResponse {
  image: string;
  width: number;
  height: number;
}

export interface CropSelection {
  x: number;
  y: number;
  width: number;
  height: number;
}
