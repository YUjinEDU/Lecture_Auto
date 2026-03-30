"use client";

import { useEffect, useState, useCallback } from "react";
import type { ScriptResponse } from "../lib/types";
import { fetchScripts } from "../lib/api";

export function useScripts(jobId: string): {
  scripts: ScriptResponse[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
  updateLocal: (slideNumber: number, updated: ScriptResponse) => void;
} {
  const [scripts, setScripts] = useState<ScriptResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchScripts(jobId);
      setScripts(data);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch scripts";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  const updateLocal = useCallback(
    (slideNumber: number, updated: ScriptResponse) => {
      setScripts((prev) =>
        prev.map((s) => (s.slide_number === slideNumber ? updated : s)),
      );
    },
    [],
  );

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { scripts, loading, error, refetch, updateLocal };
}
