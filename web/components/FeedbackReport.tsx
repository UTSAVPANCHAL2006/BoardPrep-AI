"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { FeedbackReport, FeedbackScores } from "@/lib/types";
import { DafFlagsBanner } from "./DafFlagsBanner";

const SCORE_LABELS: Record<keyof FeedbackScores, string> = {
  clarity: "Clarity",
  structure: "Structure",
  daf_consistency: "DAF Consistency",
  subject_depth: "Subject Depth",
  current_affairs: "Current Affairs",
  confidence: "Confidence",
};

function ScoreCard({ label, score }: { label: string; score: number }) {
  const pct = (score / 10) * 100;
  const color = score >= 7 ? "from-emerald-500 to-emerald-400" : score >= 5 ? "from-saffron to-saffron-light" : "from-red-500 to-red-400";
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-slate-400">{label}</p>
        <p className="font-display text-2xl font-bold text-slate-100">{score}</p>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-navy-border">
        <div
          className={`h-full rounded-full bg-gradient-to-r ${color} transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function FeedbackReportView({
  report,
  dafFlags,
}: {
  report: FeedbackReport;
  dafFlags: FeedbackReport["daf_flags"];
}) {
  const scores = report.scores;
  const chartData = scores
    ? (Object.keys(SCORE_LABELS) as (keyof FeedbackScores)[]).map((key) => ({
        name: SCORE_LABELS[key],
        score: scores[key] ?? 0,
      }))
    : [];

  const avgScore = chartData.length
    ? (chartData.reduce((s, d) => s + d.score, 0) / chartData.length).toFixed(1)
    : null;

  return (
    <div className="space-y-6">
      {/* Hero summary */}
      <div className="gradient-border">
        <div className="inner p-8">
          <div className="flex flex-col items-start justify-between gap-6 md:flex-row md:items-center">
            <div>
              <p className="section-label">Interview Complete</p>
              <h2 className="mt-2 font-display text-3xl font-bold">Your Board Report</h2>
              <p className="mt-3 max-w-xl text-slate-400">{report.overall_summary}</p>
            </div>
            {avgScore && (
              <div className="flex h-28 w-28 flex-shrink-0 flex-col items-center justify-center rounded-full bg-gradient-to-br from-saffron/20 to-saffron/5 ring-2 ring-saffron/30">
                <p className="font-display text-4xl font-bold text-saffron">{avgScore}</p>
                <p className="text-[10px] uppercase tracking-widest text-slate-500">/ 10 avg</p>
              </div>
            )}
          </div>
        </div>
      </div>

      <DafFlagsBanner flags={dafFlags || []} />

      {/* Score cards grid */}
      {scores && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {(Object.keys(SCORE_LABELS) as (keyof FeedbackScores)[]).map((key) => (
            <ScoreCard key={key} label={SCORE_LABELS[key]} score={scores[key] ?? 0} />
          ))}
        </div>
      )}

      {chartData.length > 0 && (
        <div className="glass-card">
          <h3 className="mb-6 font-display text-lg font-semibold">Performance Overview</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} barSize={32}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="name" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 10]} tick={{ fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ background: "#132847", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "12px" }}
                  labelStyle={{ color: "#e2e8f0" }}
                  cursor={{ fill: "rgba(255,153,51,0.08)" }}
                />
                <Bar dataKey="score" fill="url(#saffronGrad)" radius={[8, 8, 0, 0]} />
                <defs>
                  <linearGradient id="saffronGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#FFB366" />
                    <stop offset="100%" stopColor="#FF9933" />
                  </linearGradient>
                </defs>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="glass-card border-emerald-500/20">
          <div className="mb-4 flex items-center gap-2">
            <span className="text-lg">✅</span>
            <h3 className="font-semibold text-emerald-300">Strengths</h3>
          </div>
          <ul className="space-y-2">
            {report.strengths?.map((s, i) => (
              <li key={i} className="flex gap-2 text-sm text-slate-300">
                <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-emerald-400" />
                {s}
              </li>
            ))}
          </ul>
        </div>
        <div className="glass-card border-amber-500/20">
          <div className="mb-4 flex items-center gap-2">
            <span className="text-lg">📈</span>
            <h3 className="font-semibold text-amber-300">Areas to Improve</h3>
          </div>
          <ul className="space-y-2">
            {report.improvements?.map((s, i) => (
              <li key={i} className="flex gap-2 text-sm text-slate-300">
                <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-amber-400" />
                {s}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {report.phase_breakdown && (
        <div className="glass-card">
          <h3 className="mb-4 font-display text-lg font-semibold">Phase-wise Breakdown</h3>
          <div className="grid gap-3 md:grid-cols-2">
            {Object.entries(report.phase_breakdown).map(([phase, text]) => (
              <div key={phase} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-saffron/70">
                  {phase.replace(/_/g, " ")}
                </p>
                <p className="mt-2 text-sm leading-relaxed text-slate-400">{text}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
