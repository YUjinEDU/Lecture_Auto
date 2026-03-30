"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import type { ScriptResponse } from "../lib/types";

interface ScriptEditorProps {
  script: ScriptResponse | null;
  onSave: (text: string) => Promise<void>;
  disabled: boolean;
}

type SaveStatus = "idle" | "saving" | "saved";

export default function ScriptEditor({
  script,
  onSave,
  disabled,
}: ScriptEditorProps) {
  const [value, setValue] = useState(script?.script ?? "");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync external script changes into local state
  useEffect(() => {
    setValue(script?.script ?? "");
    setSaveStatus("idle");
  }, [script?.slide_number, script?.script]);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const doSave = useCallback(
    async (text: string) => {
      if (disabled) return;
      if (text === (script?.script ?? "")) return;

      setSaveStatus("saving");
      try {
        await onSave(text);
        setSaveStatus("saved");
        if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
        savedTimerRef.current = setTimeout(() => {
          setSaveStatus("idle");
        }, 2_000);
      } catch {
        setSaveStatus("idle");
      }
    },
    [disabled, script?.script, onSave],
  );

  const handleBlur = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      doSave(value);
    }, 500);
  }, [value, doSave]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        doSave(value);
      }
    },
    [value, doSave],
  );

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center justify-between px-4 py-1">
        <span className="text-sm font-semibold leading-[1.4]">
          Script
        </span>
        {saveStatus === "saving" && (
          <span className="text-xs text-[#9CA3AF]">Saving...</span>
        )}
        {saveStatus === "saved" && (
          <span className="text-xs text-[#16A34A] flex items-center gap-1">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M20 6 9 17l-5-5" />
            </svg>
            Saved
          </span>
        )}
      </div>

      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        placeholder="Script will appear after generation..."
        readOnly={disabled}
        className={`flex-1 min-h-[200px] resize-y text-base font-normal leading-[1.75] border border-[#D1D5DB] focus:ring-2 focus:ring-[#2563EB] focus:outline-none rounded-lg p-4 mx-4 mb-2
          ${disabled ? "bg-gray-100 cursor-not-allowed" : "bg-white"}`}
      />
    </div>
  );
}
