"use client";

import { useState, useCallback, useRef } from "react";

// Same-origin proxy — the homepage server forwards to GPU_API_URL.
// See portal/app/api/gpu/[...path]/route.ts.
const GPU_API_URL = "/api/gpu";

interface AudioPreviewProps {
  jobId: string;
  slideNumber: number;
  hasAudio: boolean;
  onRegenerate: (slideNumber: number) => void;
}

export default function AudioPreview({
  jobId,
  slideNumber,
  hasAudio,
  onRegenerate,
}: AudioPreviewProps) {
  const [regenerating, setRegenerating] = useState(false);
  const [audioKey, setAudioKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const audioSrc = `${GPU_API_URL}/jobs/${jobId}/audio/${slideNumber}/wav`;

  const handleRegenerate = useCallback(async () => {
    setRegenerating(true);
    setError(null);

    // Cancel any previous in-flight request
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(
        `${GPU_API_URL}/jobs/${jobId}/tts/${slideNumber}/regenerate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
        },
      );

      if (!res.ok) {
        const detail = await res
          .json()
          .then((b) => b.detail ?? b.message ?? res.statusText)
          .catch(() => res.statusText);
        throw new Error(`Regeneration failed: ${detail}`);
      }

      // Notify parent
      onRegenerate(slideNumber);

      // Wait briefly then force audio reload
      setTimeout(() => {
        setAudioKey((k) => k + 1);
        setRegenerating(false);
      }, 3000);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const message =
        err instanceof Error ? err.message : "Regeneration failed";
      setError(message);
      setRegenerating(false);
    }
  }, [jobId, slideNumber, onRegenerate]);

  return (
    <div className="flex items-center gap-2">
      {hasAudio ? (
        <audio
          key={audioKey}
          controls
          preload="none"
          className="w-full h-10"
          src={audioSrc}
        >
          Your browser does not support the audio element.
        </audio>
      ) : (
        <span className="text-sm text-[#9CA3AF] flex-1">
          Audio not generated yet
        </span>
      )}

      <button
        type="button"
        onClick={handleRegenerate}
        disabled={regenerating}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium whitespace-nowrap transition-colors
          ${
            regenerating
              ? "text-[#9CA3AF] cursor-not-allowed"
              : "text-[#2563EB] hover:bg-[#2563EB]/5"
          }`}
      >
        {regenerating ? (
          <>
            <svg
              className="animate-spin"
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
            Regenerating...
          </>
        ) : (
          <>
            {/* RotateCcw icon (Lucide) */}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
            </svg>
            Regenerate Audio
          </>
        )}
      </button>

      {error && (
        <span className="text-xs text-[#DC2626] ml-1">{error}</span>
      )}
    </div>
  );
}
