export interface ScriptResponse {
  slide_index: number;
  slide_number: number;
  target_seconds: number;
  script: string;
  keywords: string[];
  transition_to_next: string;
  edited: boolean;
  edited_at: string | null;
}

export interface ProgressEvent {
  job_id: string;
  stage: string;
  current: number;
  total: number;
  percent: number;
  status: string;
}

export type SlideStatus = "generating" | "generated" | "edited" | "empty" | "error";
