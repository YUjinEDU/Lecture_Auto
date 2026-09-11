"use client";

import { useState, useRef, useCallback, useEffect } from "react";

// Same-origin proxy — the homepage server forwards to GPU_API_URL.
// See portal/app/api/gpu/[...path]/route.ts.
const GPU_API_URL = "/api/gpu";

interface VoiceRecorderProps {
  onRegistered: (status: { registered: boolean }) => void;
}

interface VoiceStatus {
  professor_id: string;
  registered: boolean;
}

export default function VoiceRecorder({ onRegistered }: VoiceRecorderProps) {
  const [recording, setRecording] = useState(false);
  const [countdown, setCountdown] = useState(3);
  const [uploading, setUploading] = useState(false);
  const [registered, setRegistered] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Check registration on mount
  useEffect(() => {
    async function checkStatus() {
      try {
        const res = await fetch(
          `${GPU_API_URL}/jobs/voice/status?professor_id=default`,
        );
        if (res.ok) {
          const data: VoiceStatus = await res.json();
          if (data.registered) {
            setRegistered(true);
            onRegistered({ registered: true });
          }
        }
      } catch {
        // Silently fail -- voice not registered yet
      }
    }
    checkStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (countdownTimerRef.current) {
        clearInterval(countdownTimerRef.current);
      }
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
    };
  }, []);

  const uploadAudio = useCallback(
    async (blob: Blob, filename: string) => {
      setUploading(true);
      setError(null);
      try {
        const formData = new FormData();
        formData.append("audio_file", blob, filename);
        formData.append("professor_id", "default");

        const res = await fetch(`${GPU_API_URL}/jobs/voice/register`, {
          method: "POST",
          body: formData,
        });

        if (!res.ok) {
          const detail = await res
            .json()
            .then((b) => b.detail ?? b.message ?? res.statusText)
            .catch(() => res.statusText);
          throw new Error(`Registration failed: ${detail}`);
        }

        setRegistered(true);
        onRegistered({ registered: true });
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Voice registration failed";
        setError(message);
      } finally {
        setUploading(false);
      }
    },
    [onRegistered],
  );

  const startRecording = useCallback(async () => {
    setError(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
      });
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        stream.getTracks().forEach((t) => t.stop());
        uploadAudio(blob, "voice_recording.webm");
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setRecording(true);
      setCountdown(3);

      // Countdown timer
      let remaining = 3;
      countdownTimerRef.current = setInterval(() => {
        remaining -= 1;
        setCountdown(remaining);
        if (remaining <= 0) {
          if (countdownTimerRef.current) {
            clearInterval(countdownTimerRef.current);
            countdownTimerRef.current = null;
          }
        }
      }, 1000);

      // Auto-stop after 3 seconds
      setTimeout(() => {
        if (recorder.state === "recording") {
          recorder.stop();
        }
        setRecording(false);
        if (countdownTimerRef.current) {
          clearInterval(countdownTimerRef.current);
          countdownTimerRef.current = null;
        }
      }, 3000);
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Could not access microphone. Please check browser permissions.";
      setError(message);
    }
  }, [uploadAudio]);

  const handleFileUpload = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      uploadAudio(file, file.name);
      // Reset input so same file can be re-selected
      e.target.value = "";
    },
    [uploadAudio],
  );

  const handleReRecord = useCallback(() => {
    setRegistered(false);
    setError(null);
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  // Registered state
  if (registered && !recording && !uploading) {
    return (
      <div className="rounded-lg border border-[#E5E7EB] p-4 flex items-center gap-3">
        {/* Green checkmark */}
        <div className="w-8 h-8 rounded-full bg-[#16A34A] flex items-center justify-center shrink-0">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="white"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M20 6 9 17l-5-5" />
          </svg>
        </div>
        <span className="text-sm font-semibold text-[#16A34A]">
          Voice registered
        </span>
        <button
          type="button"
          onClick={handleReRecord}
          className="ml-auto text-xs text-[#9CA3AF] underline hover:text-[#6B7280] transition-colors"
        >
          Re-record
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[#E5E7EB] p-4">
      <div className="flex items-center gap-3">
        {recording ? (
          /* Recording state */
          <div className="flex items-center gap-3">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#DC2626] opacity-75" />
              <span className="relative inline-flex rounded-full h-3 w-3 bg-[#DC2626]" />
            </span>
            <span className="text-2xl font-semibold tabular-nums w-8 text-center">
              {countdown}
            </span>
            <span className="text-sm text-[#9CA3AF]">Recording...</span>
          </div>
        ) : uploading ? (
          /* Uploading state */
          <div className="flex items-center gap-3">
            <svg
              className="animate-spin text-[#2563EB]"
              xmlns="http://www.w3.org/2000/svg"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
            <span className="text-sm text-[#9CA3AF]">Uploading...</span>
          </div>
        ) : (
          /* Default state: Record + Upload buttons */
          <>
            <button
              type="button"
              onClick={startRecording}
              className="flex items-center gap-2 h-11 px-4 rounded-lg bg-[#2563EB] text-white text-sm font-medium hover:bg-[#1D4ED8] transition-colors"
            >
              {/* Mic icon (Lucide) */}
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" x2="12" y1="19" y2="22" />
              </svg>
              Record Voice (3s)
            </button>

            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-2 h-11 px-4 rounded-lg border border-[#D1D5DB] text-sm font-medium text-gray-700 hover:bg-[#F8F9FA] transition-colors"
            >
              {/* Upload icon (Lucide) */}
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" x2="12" y1="3" y2="15" />
              </svg>
              Upload WAV
            </button>

            <input
              ref={fileInputRef}
              type="file"
              accept=".wav,audio/wav"
              onChange={handleFileUpload}
              className="hidden"
            />
          </>
        )}
      </div>

      {/* Error message */}
      {error && (
        <p className="mt-3 text-sm text-[#DC2626]">{error}</p>
      )}
    </div>
  );
}
