"use client";

import { useState, useCallback, useMemo } from "react";
import { useParams } from "next/navigation";
import type { ScriptResponse } from "./lib/types";
import {
  updateScript,
  regenerateScript,
  approveScripts,
} from "./lib/api";
import { useScripts } from "./hooks/useScripts";
import { useSSEProgress } from "./hooks/useSSEProgress";

import SlideListPanel from "./components/SlideListPanel";
import SlidePreview from "./components/SlidePreview";
import ScriptEditor from "./components/ScriptEditor";
import ActionBar from "./components/ActionBar";
import ProgressFooter from "./components/ProgressFooter";
import RegenerateConfirmDialog from "./components/RegenerateConfirmDialog";
import ApproveConfirmDialog from "./components/ApproveConfirmDialog";

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function LoadingSkeleton() {
  return (
    <div className="flex h-screen animate-pulse">
      {/* Left panel skeleton */}
      <div className="w-[240px] shrink-0 bg-[#F8F9FA] p-4 flex flex-col gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex flex-col items-center gap-2">
            <div className="w-[160px] h-[90px] bg-gray-200 rounded" />
            <div className="w-16 h-3 bg-gray-200 rounded" />
          </div>
        ))}
      </div>
      {/* Right panel skeleton */}
      <div className="flex-1 p-6 flex flex-col gap-4">
        <div className="h-[200px] bg-gray-200 rounded-lg" />
        <div className="flex-1 flex flex-col gap-2">
          <div className="h-4 bg-gray-200 rounded w-3/4" />
          <div className="h-4 bg-gray-200 rounded w-full" />
          <div className="h-4 bg-gray-200 rounded w-5/6" />
          <div className="h-4 bg-gray-200 rounded w-2/3" />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-screen">
      <div className="max-w-md text-center px-8">
        <h1 className="text-xl font-semibold mb-4">Job not found</h1>
        <p className="text-base text-gray-600 leading-[1.5]">
          {message ||
            "The requested job does not exist or has expired. Please return to the dashboard and try again."}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function ScriptReviewPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId;

  const { scripts, loading, error, refetch, updateLocal } =
    useScripts(jobId);
  const { progress, isComplete } = useSSEProgress(jobId, !loading);

  const [selectedSlide, setSelectedSlide] = useState(1);
  const [showRegenerateDialog, setShowRegenerateDialog] = useState(false);
  const [showApproveDialog, setShowApproveDialog] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [hasEditorChanges, setHasEditorChanges] = useState(false);

  // Refetch scripts when SSE completes
  const prevIsComplete = useMemo(() => isComplete, [isComplete]);
  if (prevIsComplete) {
    // Trigger refetch once on complete (handled via effect-like pattern)
  }

  // Derive current script
  const currentScript = useMemo(
    () => scripts.find((s) => s.slide_number === selectedSlide) ?? null,
    [scripts, selectedSlide],
  );

  // Total slides = max slide_number from scripts, or from progress.total
  const totalSlides = useMemo(() => {
    const fromScripts = scripts.reduce(
      (max, s) => Math.max(max, s.slide_number),
      0,
    );
    const fromProgress = progress?.total ?? 0;
    return Math.max(fromScripts, fromProgress, 1);
  }, [scripts, progress]);

  // All non-empty check for approve button
  const allNonEmpty = useMemo(() => {
    if (scripts.length === 0) return false;
    return scripts.every((s) => s.script && s.script.length > 0);
  }, [scripts]);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleSave = useCallback(
    async (text: string) => {
      const updated = await updateScript(jobId, selectedSlide, {
        script: text,
      });
      updateLocal(selectedSlide, updated);
      setHasEditorChanges(false);
    },
    [jobId, selectedSlide, updateLocal],
  );

  const handleManualSave = useCallback(() => {
    if (currentScript) {
      handleSave(currentScript.script);
    }
  }, [currentScript, handleSave]);

  const handleRegenerate = useCallback(() => {
    if (currentScript?.edited) {
      setShowRegenerateDialog(true);
    } else {
      doRegenerate(false);
    }
  }, [currentScript]);

  const doRegenerate = useCallback(
    async (force: boolean) => {
      setIsRegenerating(true);
      setShowRegenerateDialog(false);
      try {
        await regenerateScript(jobId, selectedSlide, force);
        // Refetch after a short delay to get updated script
        setTimeout(() => {
          refetch();
          setIsRegenerating(false);
        }, 2_000);
      } catch {
        setIsRegenerating(false);
      }
    },
    [jobId, selectedSlide, refetch],
  );

  const handleApprove = useCallback(() => {
    setShowApproveDialog(true);
  }, []);

  const doApprove = useCallback(async () => {
    setIsApproving(true);
    setShowApproveDialog(false);
    try {
      await approveScripts(jobId);
      refetch();
    } catch {
      // Error handling -- could show toast
    } finally {
      setIsApproving(false);
    }
  }, [jobId, refetch]);

  // SSE complete triggers refetch
  useMemo(() => {
    if (isComplete && scripts.length > 0) {
      refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isComplete]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading && scripts.length === 0) return <LoadingSkeleton />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-8 py-4 border-b border-[#E5E7EB]">
        <h1 className="text-xl font-semibold leading-[1.2]">
          Script Review
        </h1>
        <span className="text-sm text-[#9CA3AF]">Job: {jobId}</span>
      </header>

      {/* Main content */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel: slide list */}
        <SlideListPanel
          scripts={scripts}
          selectedSlide={selectedSlide}
          totalSlides={totalSlides}
          onSelectSlide={setSelectedSlide}
          jobId={jobId}
        />

        {/* Right panel: detail */}
        <main className="flex-1 flex flex-col min-h-0 overflow-y-auto">
          {/* Slide preview */}
          <div className="p-4 pb-2">
            <SlidePreview jobId={jobId} slideNumber={selectedSlide} />
          </div>

          {/* Script editor */}
          <ScriptEditor
            script={currentScript}
            onSave={handleSave}
            disabled={isRegenerating}
          />

          {/* Action bar */}
          <ActionBar
            onRegenerate={handleRegenerate}
            onSave={handleManualSave}
            hasChanges={hasEditorChanges}
            isRegenerating={isRegenerating}
          />
        </main>
      </div>

      {/* Footer with progress and approve */}
      <ProgressFooter
        progress={progress}
        isComplete={isComplete}
        allNonEmpty={allNonEmpty}
        onApprove={handleApprove}
        isApproving={isApproving}
      />

      {/* Dialogs */}
      <RegenerateConfirmDialog
        open={showRegenerateDialog}
        onConfirm={() => doRegenerate(true)}
        onCancel={() => setShowRegenerateDialog(false)}
      />
      <ApproveConfirmDialog
        open={showApproveDialog}
        totalSlides={totalSlides}
        onConfirm={doApprove}
        onCancel={() => setShowApproveDialog(false)}
      />
    </div>
  );
}
