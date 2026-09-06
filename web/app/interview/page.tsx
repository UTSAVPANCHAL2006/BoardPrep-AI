"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { InterviewRoom } from "@/components/InterviewRoom";

function InterviewContent() {
  const params = useSearchParams();
  const sessionId = params.get("session");
  if (!sessionId) return <div className="glass-card text-red-400">Missing session.</div>;
  return <InterviewRoom sessionId={sessionId} />;
}

export default function InterviewPage() {
  return (
    <Suspense fallback={<div className="glass-card text-center text-slate-400">Loading...</div>}>
      <InterviewContent />
    </Suspense>
  );
}
