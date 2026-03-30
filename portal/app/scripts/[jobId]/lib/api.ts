import type { ScriptResponse } from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_GPU_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response
      .json()
      .then((b) => b.detail ?? b.message ?? response.statusText)
      .catch(() => response.statusText);
    throw new Error(`API error ${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Script CRUD
// ---------------------------------------------------------------------------

export async function fetchScripts(jobId: string): Promise<ScriptResponse[]> {
  const res = await fetch(`${API_URL}/jobs/${jobId}/scripts`, {
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse<ScriptResponse[]>(res);
}

export async function updateScript(
  jobId: string,
  slideNumber: number,
  body: {
    script: string;
    keywords?: string[];
    transition_to_next?: string;
  },
): Promise<ScriptResponse> {
  const res = await fetch(
    `${API_URL}/jobs/${jobId}/scripts/${slideNumber}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return handleResponse<ScriptResponse>(res);
}

export async function regenerateScript(
  jobId: string,
  slideNumber: number,
  force: boolean = false,
): Promise<{
  job_id: string;
  slide_number: number;
  task_id: string;
  status: string;
}> {
  const res = await fetch(
    `${API_URL}/jobs/${jobId}/scripts/${slideNumber}/regenerate?force=${force}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    },
  );
  return handleResponse(res);
}

export async function approveScripts(jobId: string): Promise<{
  job_id: string;
  total_slides: number;
  tts_task_id: string | null;
  status: string;
}> {
  const res = await fetch(`${API_URL}/jobs/${jobId}/scripts/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return handleResponse(res);
}

// ---------------------------------------------------------------------------
// URL builders (no fetch — consumed by <img> / EventSource)
// ---------------------------------------------------------------------------

export function getSlideImageUrl(
  jobId: string,
  slideNumber: number,
): string {
  return `${API_URL}/jobs/${jobId}/slides/${slideNumber}/png`;
}

export function getProgressUrl(jobId: string): string {
  return `${API_URL}/jobs/${jobId}/scripts/progress`;
}
