"use client";

import { getSlideImageUrl } from "../lib/api";

interface SlidePreviewProps {
  jobId: string;
  slideNumber: number;
}

export default function SlidePreview({
  jobId,
  slideNumber,
}: SlidePreviewProps) {
  return (
    <div className="bg-[#F0F0F0] border border-[#E5E7EB] rounded-lg overflow-hidden">
      <img
        src={getSlideImageUrl(jobId, slideNumber)}
        alt={`Slide ${slideNumber} preview`}
        className="max-h-[360px] w-full object-contain"
      />
    </div>
  );
}
