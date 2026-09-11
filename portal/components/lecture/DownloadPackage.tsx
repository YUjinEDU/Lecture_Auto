"use client";

import { useState, useEffect } from "react";

// Same-origin proxy — the homepage server forwards to GPU_API_URL.
// See portal/app/api/gpu/[...path]/route.ts.
const GPU_API_URL = "/api/gpu";

interface DownloadPackageProps {
  jobId: string;
  enabled: boolean;
}

interface PackageInfo {
  job_id: string;
  files: string[];
  total_size_mb: number;
  download_url: string;
}

export default function DownloadPackage({
  jobId,
  enabled,
}: DownloadPackageProps) {
  const [packageInfo, setPackageInfo] = useState<PackageInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch package info when enabled
  useEffect(() => {
    if (!enabled) {
      setPackageInfo(null);
      return;
    }

    let cancelled = false;

    async function fetchPackage() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${GPU_API_URL}/jobs/${jobId}/package`);
        if (!res.ok) {
          const detail = await res
            .json()
            .then((b) => b.detail ?? b.message ?? res.statusText)
            .catch(() => res.statusText);
          throw new Error(detail);
        }
        const data: PackageInfo = await res.json();
        if (!cancelled) {
          setPackageInfo(data);
        }
      } catch (err) {
        if (!cancelled) {
          const message =
            err instanceof Error ? err.message : "Failed to load package info";
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchPackage();
    return () => {
      cancelled = true;
    };
  }, [jobId, enabled]);

  const handleDownload = () => {
    const downloadUrl = `${GPU_API_URL}/jobs/${jobId}/package/download`;
    // Use hidden anchor for proper download behavior
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `lecture_${jobId}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div className="rounded-lg border border-[#E5E7EB] p-4">
      <button
        type="button"
        onClick={handleDownload}
        disabled={!enabled || loading}
        className={`flex items-center justify-center gap-2 w-full h-11 rounded-lg text-sm font-medium transition-colors
          ${
            enabled && !loading
              ? "bg-[#2563EB] text-white hover:bg-[#1D4ED8]"
              : "bg-[#2563EB] text-white opacity-50 cursor-not-allowed"
          }`}
      >
        {/* Download icon (Lucide) */}
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
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" x2="12" y1="15" y2="3" />
        </svg>
        Download Package
      </button>

      {/* Package info */}
      {loading && (
        <p className="mt-2 text-xs text-[#9CA3AF]">Loading package info...</p>
      )}
      {packageInfo && (
        <p className="mt-2 text-xs text-[#9CA3AF] text-center">
          {packageInfo.files.length} files, {packageInfo.total_size_mb.toFixed(1)} MB
        </p>
      )}
      {error && (
        <p className="mt-2 text-xs text-[#DC2626]">{error}</p>
      )}
      {!enabled && !loading && (
        <p className="mt-2 text-xs text-[#9CA3AF] text-center">
          Complete TTS generation to download
        </p>
      )}
    </div>
  );
}
