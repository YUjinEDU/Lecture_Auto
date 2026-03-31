"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams } from "next/navigation";
import VoiceRecorder from "../../../../components/lecture/VoiceRecorder";
import AudioPreview from "../../../../components/lecture/AudioPreview";
import DownloadPackage from "../../../../components/lecture/DownloadPackage";
import TTSProgressFooter from "../../../../components/lecture/TTSProgressFooter";

const GPU_API_URL =
  process.env.NEXT_PUBLIC_GPU_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ScriptResponse {
  slide_index: number;
  slide_number: number;
  target_seconds: number;
  script: string;
  keywords: string[];
  transition_to_next: string;
  edited: boolean;
  edited_at: string | null;
}

type AudioStatus = "ready" | "generating" | "none";

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function LoadingSkeleton() {
  return (
    <div className="flex h-screen animate-pulse">
      <div className="w-[240px] shrink-0 bg-[#F8F9FA] p-4 flex flex-col gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex flex-col items-center gap-2">
            <div className="w-[160px] h-[90px] bg-gray-200 rounded" />
            <div className="w-16 h-3 bg-gray-200 rounded" />
          </div>
        ))}
      </div>
      <div className="flex-1 p-6 flex flex-col gap-4">
        <div className="h-[200px] bg-gray-200 rounded-lg" />
        <div className="flex-1 flex flex-col gap-2">
          <div className="h-4 bg-gray-200 rounded w-3/4" />
          <div className="h-4 bg-gray-200 rounded w-full" />
          <div className="h-4 bg-gray-200 rounded w-5/6" />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-screen">
      <div className="max-w-md text-center px-8">
        <h1 className="text-xl font-semibold mb-4">Job not found</h1>
        <p className="text-base text-gray-600 leading-[1.5]">
          {message ||
            "The requested job does not exist or has expired. Please return to the dashboard and try again."}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audio status badges
// ---------------------------------------------------------------------------

const AUDIO_BADGE: Record<AudioStatus, { label: string; className: string }> = {
  ready: {
    label: "Audio Ready",
    className: "bg-[#16A34A] text-white",
  },
  generating: {
    label: "Generating...",
    className: "text-[#9CA3AF] animate-pulse",
  },
  none: {
    label: "No Audio",
    className: "bg-[#9CA3AF]/20 text-[#9CA3AF]",
  },
};

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function TTSReviewPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId;

  // State
  const [scripts, setScripts] = useState<ScriptResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSlide, setSelectedSlide] = useState(1);
  const [voiceRegistered, setVoiceRegistered] = useState(false);
  const [ttsComplete, setTtsComplete] = useState(false);
  const [audioReady, setAudioReady] = useState<Record<number, boolean>>({});

  // Fetch scripts on mount
  useEffect(() => {
    let cancelled = false;

    async function fetchScripts() {
      setLoading(true);
      try {
        const res = await fetch(`${GPU_API_URL}/jobs/${jobId}/scripts`);
        if (!res.ok) {
          const detail = await res
            .json()
            .then((b) => b.detail ?? b.message ?? res.statusText)
            .catch(() => res.statusText);
          throw new Error(detail);
        }
        const data: ScriptResponse[] = await res.json();
        if (!cancelled) {
          setScripts(data);
          if (data.length > 0) {
            setSelectedSlide(data[0].slide_number);
          }
        }
      } catch (err) {
        if (!cancelled) {
          const message =
            err instanceof Error ? err.message : "Failed to load scripts";
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchScripts();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  // Check audio availability for each slide
  useEffect(() => {
    if (scripts.length === 0) return;
    let cancelled = false;

    async function checkAudio() {
      const results: Record<number, boolean> = {};
      await Promise.all(
        scripts.map(async (s) => {
          try {
            const res = await fetch(
              `${GPU_API_URL}/jobs/${jobId}/audio/${s.slide_number}/wav`,
              { method: "HEAD" },
            );
            results[s.slide_number] = res.ok;
          } catch {
            results[s.slide_number] = false;
          }
        }),
      );
      if (!cancelled) {
        setAudioReady(results);
        // If all audio is ready, consider TTS complete
        const allReady = scripts.every((s) => results[s.slide_number]);
        if (allReady) {
          setTtsComplete(true);
        }
      }
    }

    checkAudio();
    return () => {
      cancelled = true;
    };
  }, [jobId, scripts]);

  // Check voice registration on mount
  useEffect(() => {
    async function checkVoice() {
      try {
        const res = await fetch(
          `${GPU_API_URL}/jobs/voice/status?professor_id=default`,
        );
        if (res.ok) {
          const data = await res.json();
          if (data.registered) {
            setVoiceRegistered(true);
          }
        }
      } catch {
        // Voice not registered
      }
    }
    checkVoice();
  }, []);

  // Derived state
  const totalSlides = useMemo(
    () =>
      scripts.reduce((max, s) => Math.max(max, s.slide_number), 0) || 1,
    [scripts],
  );

  const currentScript = useMemo(
    () => scripts.find((s) => s.slide_number === selectedSlide) ?? null,
    [scripts, selectedSlide],
  );

  const slides = useMemo(
    () => Array.from({ length: totalSlides }, (_, i) => i + 1),
    [totalSlides],
  );

  const scriptMap = useMemo(() => {
    const map = new Map<number, ScriptResponse>();
    for (const s of scripts) {
      map.set(s.slide_number, s);
    }
    return map;
  }, [scripts]);

  // Handlers
  const handleVoiceRegistered = useCallback(
    (status: { registered: boolean }) => {
      setVoiceRegistered(status.registered);
    },
    [],
  );

  const handleTtsComplete = useCallback(() => {
    setTtsComplete(true);
    // Refresh audio status
    const updatedAudio: Record<number, boolean> = {};
    for (const s of scripts) {
      updatedAudio[s.slide_number] = true;
    }
    setAudioReady(updatedAudio);
  }, [scripts]);

  const handleRegenerate = useCallback(
    (slideNumber: number) => {
      // Mark as generating, then re-check after delay
      setAudioReady((prev) => ({ ...prev, [slideNumber]: false }));
      setTimeout(() => {
        setAudioReady((prev) => ({ ...prev, [slideNumber]: true }));
      }, 5000);
    },
    [],
  );

  const getAudioStatus = useCallback(
    (slideNumber: number): AudioStatus => {
      if (audioReady[slideNumber]) return "ready";
      if (!ttsComplete) return "generating";
      return "none";
    },
    [audioReady, ttsComplete],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading && scripts.length === 0) return <LoadingSkeleton />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-8 py-4 border-b border-[#E5E7EB]">
        <h1 className="text-xl font-semibold leading-[1.2]">
          TTS Audio Review
        </h1>
        <span className="text-sm text-[#9CA3AF]">Job: {jobId}</span>
      </header>

      {/* Voice Setup Section */}
      {!voiceRegistered && (
        <section className="px-8 py-4 border-b border-[#E5E7EB] bg-[#F8F9FA]">
          <h2 className="text-sm font-semibold mb-3 text-gray-700">
            Voice Setup
          </h2>
          <VoiceRecorder onRegistered={handleVoiceRegistered} />
        </section>
      )}

      {/* Voice registered compact indicator */}
      {voiceRegistered && (
        <section className="px-8 py-3 border-b border-[#E5E7EB]">
          <VoiceRecorder onRegistered={handleVoiceRegistered} />
        </section>
      )}

      {/* Main content: 2-panel layout */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel: slide list (desktop/tablet) */}
        <aside className="hidden md:flex flex-col w-[240px] lg:w-[240px] md:w-[180px] shrink-0 bg-[#F8F9FA] overflow-y-auto border-r border-[#E5E7EB]">
          {slides.map((n) => {
            const isSelected = n === selectedSlide;
            const audioStatus = getAudioStatus(n);
            const badge = AUDIO_BADGE[audioStatus];

            return (
              <button
                key={n}
                type="button"
                onClick={() => setSelectedSlide(n)}
                className={`flex flex-col items-center gap-1 p-2 text-left transition-colors cursor-pointer
                  ${isSelected ? "border-l-2 border-[#2563EB] bg-white" : "border-l-2 border-transparent hover:bg-[#F0F0F0]"}`}
              >
                <img
                  src={`${GPU_API_URL}/jobs/${jobId}/slides/${n}/png`}
                  alt={`Slide ${n}`}
                  className="w-[160px] h-[90px] lg:w-[160px] lg:h-[90px] md:w-[120px] md:h-[68px] object-cover rounded border border-[#E5E7EB]"
                  loading="lazy"
                />
                <span className="text-sm text-[#9CA3AF]">Slide {n}</span>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full ${badge.className}`}
                >
                  {badge.label}
                </span>
              </button>
            );
          })}
        </aside>

        {/* Mobile dropdown */}
        <div className="md:hidden px-4 py-2 border-b border-[#E5E7EB] bg-[#F8F9FA]">
          <select
            value={selectedSlide}
            onChange={(e) => setSelectedSlide(Number(e.target.value))}
            className="w-full h-10 px-3 rounded-lg border border-[#D1D5DB] bg-white text-sm"
          >
            {slides.map((n) => {
              const audioStatus = getAudioStatus(n);
              const badge = AUDIO_BADGE[audioStatus];
              return (
                <option key={n} value={n}>
                  Slide {n} - {badge.label}
                </option>
              );
            })}
          </select>
        </div>

        {/* Right panel: detail */}
        <main className="flex-1 flex flex-col min-h-0 overflow-y-auto">
          {/* Slide preview */}
          <div className="p-4 pb-2">
            <div className="rounded-lg border border-[#E5E7EB] bg-[#F0F0F0] overflow-hidden">
              <img
                src={`${GPU_API_URL}/jobs/${jobId}/slides/${selectedSlide}/png`}
                alt={`Slide ${selectedSlide}`}
                className="w-full max-h-[360px] object-contain"
              />
            </div>
          </div>

          {/* Script text (readonly) */}
          <div className="px-4 pb-2">
            <div className="rounded-lg border border-[#E5E7EB] p-4 bg-white">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">
                Script
              </h3>
              {currentScript?.script ? (
                <div className="text-base leading-[1.75] whitespace-pre-wrap text-gray-800">
                  {currentScript.script}
                </div>
              ) : (
                <p className="text-sm text-[#9CA3AF] italic">
                  No script available for this slide.
                </p>
              )}
            </div>
          </div>

          {/* Audio preview */}
          <div className="px-4 pb-4">
            <div className="rounded-lg border border-[#E5E7EB] p-4 bg-white">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">
                Audio
              </h3>
              <AudioPreview
                jobId={jobId}
                slideNumber={selectedSlide}
                hasAudio={audioReady[selectedSlide] ?? false}
                onRegenerate={handleRegenerate}
              />
            </div>
          </div>
        </main>
      </div>

      {/* Footer: TTSProgress during generation, DownloadPackage after completion */}
      {!ttsComplete ? (
        <TTSProgressFooter jobId={jobId} onComplete={handleTtsComplete} />
      ) : (
        <footer className="sticky bottom-0 bg-white border-t border-[#E5E7EB] px-8 py-3 z-10">
          <DownloadPackage jobId={jobId} enabled={ttsComplete} />
        </footer>
      )}
    </div>
  );
}
