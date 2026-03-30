"use client";

import { useEffect, useCallback } from "react";

interface RegenerateConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function RegenerateConfirmDialog({
  open,
  onConfirm,
  onCancel,
}: RegenerateConfirmDialogProps) {
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
          Overwrite edited script?
        </h2>
        <p className="text-base leading-[1.5] text-gray-600 mb-6">
          You have manually edited this slide&apos;s script. Regenerating
          will replace your edits. This cannot be undone.
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
            className="px-4 py-2 text-sm bg-[#DC2626] text-white rounded-lg hover:bg-[#B91C1C] transition-colors"
          >
            Regenerate Anyway
          </button>
        </div>
      </div>
    </div>
  );
}
