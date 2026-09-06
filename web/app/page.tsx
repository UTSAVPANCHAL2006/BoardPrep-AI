"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { uploadDaf } from "@/lib/api";
import type { InterviewMode } from "@/lib/types";

const MODES: { id: InterviewMode; label: string; qs: string; desc: string }[] = [
  { id: "quick", label: "Quick Drill", qs: "4 questions", desc: "~10 min practice" },
  { id: "full", label: "Full Board", qs: "12 questions", desc: "Full simulation" },
];

const FEATURES = [
  {
    title: "Voice Interview",
    desc: "Speak in Hindi, English, or Hinglish — the panel listens and responds.",
  },
  {
    title: "Daily Current Affairs",
    desc: "Curated headlines with GS notes and a spoken classroom briefing.",
  },
  {
    title: "DAF-Aware Questions",
    desc: "Questions anchored to your uploaded Detailed Application Form.",
  },
  {
    title: "Scored Feedback",
    desc: "Structured rubric report after each mock session.",
  },
];

export default function HomePage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<InterviewMode>("full");
  const [loading, setLoading] = useState(false);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState("");

  const onFile = useCallback((f: File | null) => {
    if (f && f.type === "application/pdf") setFile(f);
  }, []);

  useEffect(() => {
    const hash = window.location.hash.replace("#", "");
    if (!hash) return;
    const timer = setTimeout(() => {
      document.getElementById(hash)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
    return () => clearTimeout(timer);
  }, []);

  async function onSubmit() {
    if (!file) {
      setError("Please upload your DAF PDF to continue.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await uploadDaf(file, mode);
      router.push(`/interview?session=${res.session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-16">
      <section className="grid items-center gap-12 pt-4 lg:grid-cols-2 lg:gap-16">
        <div className="animate-fade-up space-y-6">
          <p className="section-label">UPSC Personality Test · Prototype</p>
          <h1 className="font-display text-4xl font-bold leading-tight tracking-tight md:text-5xl lg:text-6xl">
            Practice the{" "}
            <span className="bg-gradient-to-r from-saffron via-saffron-light to-india-green bg-clip-text text-transparent">
              board interview
            </span>
            <br />
            with voice AI
          </h1>
          <p className="max-w-md text-lg leading-relaxed text-slate-400">
            Upload your DAF, face a four-phase mock panel, and review scored feedback — built as
            an AI engineering portfolio project for UPSC prep workflows.
          </p>
          <a
            href="/current-affairs"
            className="inline-flex items-center gap-2 text-sm font-medium text-saffron transition hover:text-saffron-light"
          >
            Browse today&apos;s current affairs
            <span aria-hidden>→</span>
          </a>
        </div>

        <div className="animate-scale-in gradient-border">
          <div className="inner space-y-6 p-8">
            <div className="text-center">
              <p className="section-label">Get started</p>
              <h2 className="mt-2 font-display text-2xl font-semibold">Upload your DAF</h2>
              <p className="mt-1 text-sm text-slate-500">PDF · UPSC Detailed Application Form</p>
            </div>

            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                onFile(e.dataTransfer.files[0] || null);
              }}
              onClick={() => document.getElementById("daf-input")?.click()}
              className={`group cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-all duration-300 ${
                drag
                  ? "scale-[1.02] border-saffron bg-saffron/10"
                  : file
                    ? "border-india-green/50 bg-india-green/5"
                    : "border-white/10 hover:border-saffron/35 hover:bg-white/[0.03]"
              }`}
            >
              <input
                id="daf-input"
                type="file"
                accept="application/pdf"
                className="hidden"
                onChange={(e) => onFile(e.target.files?.[0] || null)}
              />
              <div
                className={`mx-auto flex h-16 w-16 items-center justify-center rounded-2xl transition ${
                  file ? "bg-india-green/20" : "bg-saffron/10 group-hover:bg-saffron/15"
                }`}
              >
                {file ? (
                  <svg className="h-8 w-8 text-india-green" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  <svg className="h-8 w-8 text-saffron" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                    />
                  </svg>
                )}
              </div>
              <p className="mt-4 font-medium text-slate-200">
                {file ? file.name : "Drag and drop, or click to browse"}
              </p>
              <p className="mt-1 text-xs text-slate-500">{file ? "Ready" : "PDF up to 10 MB"}</p>
            </div>

            <div>
              <p className="mb-3 text-center text-xs font-semibold uppercase tracking-widest text-slate-500">
                Session length
              </p>
              <div className="grid grid-cols-2 gap-2">
                {MODES.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setMode(m.id)}
                    className={`rounded-xl p-3 text-center transition-all duration-200 ${
                      mode === m.id
                        ? "bg-saffron/15 ring-1 ring-saffron/45"
                        : "border border-white/[0.06] bg-white/[0.02] hover:border-saffron/25"
                    }`}
                  >
                    <p className={`text-xs font-semibold ${mode === m.id ? "text-saffron" : "text-slate-300"}`}>
                      {m.label}
                    </p>
                    <p className="mt-1 text-[10px] text-slate-500">
                      {m.qs} · {m.desc}
                    </p>
                  </button>
                ))}
              </div>
            </div>

            {error && (
              <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-center text-sm text-red-300">
                {error}
              </p>
            )}

            <button
              type="button"
              disabled={loading || !file}
              onClick={() => void onSubmit()}
              className="btn-primary w-full py-4 text-base"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-navy-deep border-t-transparent" />
                  Preparing your session...
                </span>
              ) : (
                "Start mock interview"
              )}
            </button>
          </div>
        </div>
      </section>

      <section id="features" className="scroll-mt-28">
        <div className="mb-8 text-center">
          <p className="section-label">Capabilities</p>
          <h2 className="mt-2 font-display text-3xl font-bold">What this prototype does</h2>
          <p className="mt-2 text-slate-500">End-to-end voice AI flow for UPSC personality test practice</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              className="glass-card group transition hover:border-saffron/25 hover:shadow-glow"
            >
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-saffron/10 text-sm font-bold text-saffron">
                {i + 1}
              </span>
              <p className="mt-3 font-semibold text-slate-100 transition group-hover:text-saffron">
                {f.title}
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="how-it-works" className="glass-card scroll-mt-28">
        <p className="section-label mb-2 text-center">Flow</p>
        <h2 className="mb-6 text-center font-display text-2xl font-semibold">Interview phases</h2>
        <div className="flex flex-wrap items-center justify-center gap-4 md:gap-8">
          {["DAF opening", "Subject probe", "Current affairs", "Closing", "Feedback"].map((step, i) => (
            <div key={step} className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-saffron/15 text-xs font-bold text-saffron">
                  {i + 1}
                </span>
                <span className="text-sm capitalize text-slate-300">{step}</span>
              </div>
              {i < 4 && <span className="hidden text-slate-600 md:inline">→</span>}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
