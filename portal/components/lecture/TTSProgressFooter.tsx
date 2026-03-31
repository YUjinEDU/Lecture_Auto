"use client";

import { useState, useEffect, useRef, useCallback } from "react";

const GPU_API_URL =
  process.env.NEXT_PUBLIC_GPU_API_URL ?? "http://localhost:8000";

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 3_000;

interface TTSProgressFooterProps {
  jobId: string;
  onComplete: () => void;
}

interface TTSProgressEvent {
  stage: string;
  current: number;
  total: number;
  status: string;
}

export default function TTSProgressFooter({
  jobId,
  onComplete,
}: TTSProgressFooterProps) {
  const [current, setCurrent] = useState(0);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [connected, setConnected] = useState(false);

  const esRef = useRef<EventSource | null>(null);
  const retriesRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cleanup = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    cleanup();

    const url = `${GPU_API_URL}/jobs/${jobId}/tts/progress`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      retriesRef.current = 0;
    };

    const handleEvent = (event: MessageEvent) => {
      try {
        const data: TTSProgressEvent = JSON.parse(event.data);
        setCurrent(data.current);
        setTotal(data.total);
        setStatus(data.status);
      } catch {
        // Ignore malformed events
      }
    };

    es.addEventListener("initial", handleEvent);
    es.addEventListener("progress", handleEvent);

    es.addEventListener("complete", (event: MessageEvent) => {
      try {
        const data: TTSProgressEvent = JSON.parse(event.data);
        setCurrent(data.current);
        setTotal(data.total);
        setStatus(data.status);
      } catch {
        // Ignore
      }
      cleanup();
      setConnected(false);
      onComplete();
    });

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setConnected(false);

      if (retriesRef.current < MAX_RETRIES) {
        retriesRef.current += 1;
        retryTimerRef.current = setTimeout(connect, RETRY_DELAY_MS);
      }
    };
  }, [jobId, cleanup, onComplete]);

  useEffect(() => {
    connect();
    return cleanup;
  }, [connect, cleanup]);

  const percent = total > 0 ? Math.round((current / total) * 100) : 0;

  return (
    <footer className="sticky bottom-0 h-16 bg-white border-t border-[#E5E7EB] flex items-center justify-between px-8 z-10">
      {/* Left: progress area */}
      <div className="flex items-center gap-4 flex-1 max-w-[500px]">
        <div className="flex-1 max-w-[400px] h-2 rounded-full bg-[#F8F9FA] overflow-hidden">
          <div
            className="h-full rounded-full bg-[#2563EB] transition-all duration-300"
            style={{ width: `${percent}%` }}
          />
        </div>
        <span className="text-sm text-[#9CA3AF] whitespace-nowrap">
          Generating audio... {current}/{total}
        </span>
      </div>

      {/* Right: connection status */}
      <div className="flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5">
          {connected ? (
            <span className="inline-flex rounded-full h-2.5 w-2.5 bg-[#16A34A]" />
          ) : (
            <>
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#F59E0B] opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-[#F59E0B]" />
            </>
          )}
        </span>
        {!connected && (
          <span className="text-xs text-[#F59E0B]">Reconnecting...</span>
        )}
      </div>
    </footer>
  );
}
