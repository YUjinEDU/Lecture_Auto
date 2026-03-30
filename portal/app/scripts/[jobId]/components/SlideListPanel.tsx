"use client";

import { useMemo } from "react";
import type { ScriptResponse, SlideStatus } from "../lib/types";
import { getSlideImageUrl } from "../lib/api";

interface SlideListPanelProps {
  scripts: ScriptResponse[];
  selectedSlide: number;
  totalSlides: number;
  onSelectSlide: (n: number) => void;
  jobId: string;
}

function getSlideStatus(script: ScriptResponse | undefined): SlideStatus {
  if (!script) return "empty";
  if (script.edited) return "edited";
  if (script.script && script.script.length > 0) return "generated";
  return "empty";
}

const STATUS_BADGE: Record<
  SlideStatus,
  { label: string; className: string }
> = {
  generating: {
    label: "Generating...",
    className: "text-[#9CA3AF] animate-pulse",
  },
  generated: {
    label: "Generated",
    className: "bg-[#16A34A] text-white",
  },
  edited: {
    label: "Edited",
    className: "bg-[#F59E0B] text-gray-900",
  },
  empty: {
    label: "No script",
    className: "bg-[#9CA3AF]/20 text-[#9CA3AF]",
  },
  error: {
    label: "Error",
    className: "bg-[#DC2626] text-white",
  },
};

export default function SlideListPanel({
  scripts,
  selectedSlide,
  totalSlides,
  onSelectSlide,
  jobId,
}: SlideListPanelProps) {
  const scriptMap = useMemo(() => {
    const map = new Map<number, ScriptResponse>();
    for (const s of scripts) {
      map.set(s.slide_number, s);
    }
    return map;
  }, [scripts]);

  const slides = useMemo(
    () => Array.from({ length: totalSlides }, (_, i) => i + 1),
    [totalSlides],
  );

  return (
    <>
      {/* Desktop / tablet panel */}
      <aside className="hidden md:flex flex-col w-[240px] lg:w-[240px] md:w-[180px] shrink-0 bg-[#F8F9FA] overflow-y-auto border-r border-[#E5E7EB]">
        {slides.map((n) => {
          const script = scriptMap.get(n);
          const status = getSlideStatus(script);
          const badge = STATUS_BADGE[status];
          const isSelected = n === selectedSlide;

          return (
            <button
              key={n}
              type="button"
              onClick={() => onSelectSlide(n)}
              className={`flex flex-col items-center gap-1 p-2 text-left transition-colors cursor-pointer
                ${isSelected ? "border-l-2 border-[#2563EB] bg-white" : "border-l-2 border-transparent hover:bg-[#F0F0F0]"}`}
            >
              <img
                src={getSlideImageUrl(jobId, n)}
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
          onChange={(e) => onSelectSlide(Number(e.target.value))}
          className="w-full h-10 px-3 rounded-lg border border-[#D1D5DB] bg-white text-sm"
        >
          {slides.map((n) => {
            const script = scriptMap.get(n);
            const status = getSlideStatus(script);
            const badge = STATUS_BADGE[status];
            return (
              <option key={n} value={n}>
                Slide {n} - {badge.label}
              </option>
            );
          })}
        </select>
      </div>
    </>
  );
}
