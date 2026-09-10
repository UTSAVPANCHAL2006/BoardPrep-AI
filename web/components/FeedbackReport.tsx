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

const PHASE_LABELS: Record<string, string> = {
  daf_opening: "DAF Opening",
  subject_probe: "Subject Probe",
  current_affairs: "Current Affairs",
  closing: "Closing Round",
};

function scoreBand(avg: number): { label: string; className: string } {
  if (avg >= 8) return { label: "Strong performance", className: "text-emerald-300" };
  if (avg >= 6) return { label: "Good foundation — keep refining", className: "text-saffron" };
  if (avg >= 4) return { label: "Developing — focus on structure", className: "text-amber-300" };
  return { label: "Needs focused practice", className: "text-red-300" };
}

function ScoreCard({ label, score }: { label: string; score: number }) {
  const pct = (score / 10) * 100;
  const color =
    score >= 7 ? "from-emerald-500 to-emerald-400" : score >= 5 ? "from-saffron to-saffron-light" : "from-red-500 to-red-400";
  const hint =
    score >= 7 ? "Strong" : score >= 5 ? "Adequate" : score >= 3 ? "Developing" : "Needs work";
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-slate-400">{label}</p>
          <p className="mt-0.5 text-[10px] uppercase tracking-wider text-slate-600">{hint}</p>
        </div>
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

  const avgScoreNum = chartData.length
    ? chartData.reduce((s, d) => s + d.score, 0) / chartData.length
    : null;
  const avgScore = avgScoreNum !== null ? avgScoreNum.toFixed(1) : null;
  const band = avgScoreNum !== null ? scoreBand(avgScoreNum) : null;

  const dimensionNotes = [
    { title: "DAF Alignment", text: report.daf_consistency },
    { title: "Subject Depth", text: report.subject_depth },
    { title: "Current Affairs", text: report.current_affairs_awareness },
  ].filter((d) => d.text?.trim());

  return (
    <div className="space-y-6">
      <div className="gradient-border">
        <div className="inner p-8">
          <div className="flex flex-col items-start justify-between gap-6 md:flex-row md:items-center">
            <div>
              <p className="section-label">Interview Complete</p>
              <h2 className="mt-2 font-display text-3xl font-bold">Your Board Report</h2>
              {band && (
                <p className={`mt-2 text-sm font-medium ${band.className}`}>{band.label}</p>
              )}
              <p className="mt-3 max-w-xl text-slate-400 leading-relaxed">{report.overall_summary}</p>
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

      {report.priority_actions && report.priority_actions.length > 0 && (
        <div className="glass-card border-saffron/20">
          <div className="mb-4 flex items-center gap-2">
            <span className="text-lg">🎯</span>
            <h3 className="font-semibold text-saffron">Priority Actions</h3>
          </div>
          <ol className="space-y-2">
            {report.priority_actions.map((action, i) => (
              <li key={i} className="flex gap-3 text-sm text-slate-300">
                <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-saffron/15 text-xs font-bold text-saffron">
                  {i + 1}
                </span>
                {action}
              </li>
            ))}
          </ol>
        </div>
      )}

      {scores && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {(Object.keys(SCORE_LABELS) as (keyof FeedbackScores)[]).map((key) => (
            <ScoreCard key={key} label={SCORE_LABELS[key]} score={scores[key] ?? 0} />
          ))}
        </div>
      )}

      {chartData.length > 0 && (
        <div className="glass-card">
          <h3 className="mb-2 font-display text-lg font-semibold">Performance Overview</h3>
          <p className="mb-6 text-xs text-slate-500">
            Scores are calibrated for mock practice — 5–6 means adequate for the mode; 7+ is strong.
          </p>
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

      {dimensionNotes.length > 0 && (
        <div className="grid gap-4 md:grid-cols-3">
          {dimensionNotes.map((item) => (
            <div key={item.title} className="glass-card">
              <h3 className="text-sm font-semibold text-slate-200">{item.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-400">{item.text}</p>
            </div>
          ))}
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
                  {PHASE_LABELS[phase] || phase.replace(/_/g, " ")}
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
