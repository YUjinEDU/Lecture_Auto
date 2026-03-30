"use client";

import { useEffect, useCallback } from "react";

interface ApproveConfirmDialogProps {
  open: boolean;
  totalSlides: number;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ApproveConfirmDialog({
  open,
  totalSlides,
  onConfirm,
  onCancel,
}: ApproveConfirmDialogProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    },
    [onCancel],
  );

  useEffect(() => {
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [open, handleKeyDown]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onCancel}
    >
      <div
        className="max-w-[400px] w-full bg-white rounded-xl p-6 mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-xl font-semibold leading-[1.2] mb-3">
          Approve all scripts?
        </h2>
        <p className="text-base leading-[1.5] text-gray-600 mb-6">
          This will start TTS audio generation for all {totalSlides} slides.
          You can still edit scripts after approval, but already-generated
          audio will need to be regenerated.
        </p>
        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-4 py-2 text-sm bg-[#2563EB] text-white rounded-lg hover:bg-[#1D4ED8] transition-colors"
          >
            Approve and Start TTS
          </button>
        </div>
      </div>
    </div>
  );
}
