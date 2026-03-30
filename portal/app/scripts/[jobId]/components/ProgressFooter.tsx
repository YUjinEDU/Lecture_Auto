"use client";

import type { ProgressEvent } from "../lib/types";

interface ProgressFooterProps {
  progress: ProgressEvent | null;
  isComplete: boolean;
  allNonEmpty: boolean;
  onApprove: () => void;
  isApproving: boolean;
}

export default function ProgressFooter({
  progress,
  isComplete,
  allNonEmpty,
  onApprove,
  isApproving,
}: ProgressFooterProps) {
  const percent = progress?.percent ?? 0;
  const current = progress?.current ?? 0;
  const total = progress?.total ?? 0;

  const canApprove = allNonEmpty && !isApproving;

  return (
    <footer className="sticky bottom-0 h-16 bg-white border-t border-[#E5E7EB] flex items-center justify-between px-8 z-10">
      {/* Left: progress area */}
      <div className="flex items-center gap-4 flex-1 max-w-[500px]">
        {!isComplete && progress && (
          <>
            <div className="flex-1 max-w-[400px] h-2 rounded-full bg-[#F8F9FA] overflow-hidden">
              <div
                className="h-full rounded-full bg-[#2563EB] transition-all duration-300"
                style={{ width: `${percent}%` }}
              />
            </div>
            <span className="text-sm text-[#9CA3AF] whitespace-nowrap">
              Generating scripts... {current}/{total}
            </span>
          </>
        )}
        {isComplete && (
          <span className="text-sm text-[#9CA3AF]">
            All scripts generated. Review and approve when ready.
          </span>
        )}
      </div>

      {/* Right: approve button */}
      <button
        type="button"
        onClick={onApprove}
        disabled={!canApprove}
        className={`flex items-center gap-2 h-11 px-6 rounded-lg text-sm font-medium transition-colors
          ${
            canApprove
              ? "bg-[#2563EB] text-white hover:bg-[#1D4ED8]"
              : "bg-[#2563EB] text-white opacity-50 cursor-not-allowed"
          }`}
      >
        {isApproving ? (
          <>
            {/* Spinner */}
            <svg
              className="animate-spin"
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
            Approving...
          </>
        ) : (
          <>
            {/* CheckCircle inline SVG 20px */}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <path d="m9 11 3 3L22 4" />
            </svg>
            Approve Scripts
          </>
        )}
      </button>
    </footer>
  );
}
