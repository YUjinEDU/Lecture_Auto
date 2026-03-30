"use client";

interface ActionBarProps {
  onRegenerate: () => void;
  onSave: () => void;
  hasChanges: boolean;
  isRegenerating: boolean;
}

export default function ActionBar({
  onRegenerate,
  onSave,
  hasChanges,
  isRegenerating,
}: ActionBarProps) {
  return (
    <div className="flex items-center justify-end gap-2 px-4 py-2 border-t border-[#E5E7EB]">
      {/* Regenerate button */}
      <button
        type="button"
        onClick={onRegenerate}
        disabled={isRegenerating}
        className="flex items-center gap-1.5 px-3 py-2 text-sm text-[#2563EB] hover:bg-[#2563EB]/5 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {/* RotateCcw inline SVG 16px */}
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
          className={isRegenerating ? "animate-spin" : ""}
        >
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M3 3v5h5" />
        </svg>
        {isRegenerating ? "Regenerating..." : "Regenerate"}
      </button>

      {/* Save button */}
      <button
        type="button"
        onClick={onSave}
        disabled={!hasChanges}
        className={`px-4 py-2 text-sm border rounded-lg transition-colors
          ${
            hasChanges
              ? "border-[#2563EB] text-[#2563EB] hover:bg-[#2563EB]/5"
              : "border-[#D1D5DB] text-[#9CA3AF] opacity-50 cursor-not-allowed"
          }`}
      >
        Save
      </button>
    </div>
  );
}
