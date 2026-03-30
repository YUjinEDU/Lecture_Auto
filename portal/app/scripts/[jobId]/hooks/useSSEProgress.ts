"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { ProgressEvent } from "../lib/types";
import { getProgressUrl } from "../lib/api";

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 3_000;

export function useSSEProgress(
  jobId: string,
  enabled: boolean,
): {
  progress: ProgressEvent | null;
  isConnected: boolean;
  isComplete: boolean;
} {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isComplete, setIsComplete] = useState(false);

  const retriesRef = useRef(0);
  const esRef = useRef<EventSource | null>(null);
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
    setIsConnected(false);
  }, []);

  const connect = useCallback(() => {
    cleanup();

    const url = getProgressUrl(jobId);
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      setIsConnected(true);
      retriesRef.current = 0;
    };

    const handleEvent = (event: MessageEvent) => {
      try {
        const data: ProgressEvent = JSON.parse(event.data);
        setProgress(data);
      } catch {
        // Ignore malformed events
      }
    };

    es.addEventListener("initial", handleEvent);
    es.addEventListener("progress", handleEvent);

    es.addEventListener("complete", (event: MessageEvent) => {
      try {
        const data: ProgressEvent = JSON.parse(event.data);
        setProgress(data);
      } catch {
        // Ignore
      }
      setIsComplete(true);
      cleanup();
    });

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setIsConnected(false);

      if (retriesRef.current < MAX_RETRIES) {
        retriesRef.current += 1;
        retryTimerRef.current = setTimeout(connect, RETRY_DELAY_MS);
      }
    };
  }, [jobId, cleanup]);

  useEffect(() => {
    if (enabled && !isComplete) {
      connect();
    } else {
      cleanup();
    }

    return cleanup;
  }, [enabled, isComplete, connect, cleanup]);

  return { progress, isConnected, isComplete };
}
