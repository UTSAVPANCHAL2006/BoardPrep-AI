"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { fetchFeedbackReport } from "@/lib/api";
import { FeedbackReportView } from "@/components/FeedbackReport";
import type { FeedbackReportResponse } from "@/lib/types";

function FeedbackContent() {
  const params = useSearchParams();
  const sessionId = params.get("session");
  const [data, setData] = useState<FeedbackReportResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) return;
    fetchFeedbackReport(sessionId)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load report"));
  }, [sessionId]);

  if (!sessionId) {
    return <div className="glass-card text-red-400">Missing session.</div>;
  }
  if (error) {
    return (
      <div className="glass-card space-y-4 text-center">
        <p className="text-4xl opacity-30">📋</p>
        <p className="text-red-300">{error}</p>
        <p className="text-sm text-slate-500">
          Complete the interview first — the report is generated when all questions are done.
        </p>
        <Link href={`/interview?session=${sessionId}`} className="btn-primary inline-block">
          Back to interview
        </Link>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-saffron/20 border-t-saffron" />
        <p className="text-slate-400">Generating your board report...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <FeedbackReportView report={data.report} dafFlags={data.daf_flags} />
      <div className="flex justify-center pt-4">
        <Link href="/" className="btn-primary">
          Start New Interview →
        </Link>
      </div>
    </div>
  );
}

export default function FeedbackPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-[40vh] items-center justify-center text-slate-400">Loading...</div>
    }>
      <FeedbackContent />
    </Suspense>
  );
}
