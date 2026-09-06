"use client";

import type { CABriefing } from "@/lib/types";
import { CA_VOICE_LANGUAGES, ttsCodeForVoice } from "@/lib/voice-language";
import type { AudioPlaybackState } from "@/lib/audio";
import { BrowserVoicePlayer } from "./BrowserVoicePlayer";
import { VoicePlayer } from "./VoicePlayer";

export function CaBriefingCard({
  briefing,
  compact = false,
  autoPlay = false,
  editionLabel,
  onPlaybackChange,
  hasNext = false,
  onNextStory,
  isDone = false,
}: {
  briefing: CABriefing;
  compact?: boolean;
  autoPlay?: boolean;
  editionLabel?: string;
  onPlaybackChange?: (state: AudioPlaybackState) => void;
  hasNext?: boolean;
  onNextStory?: () => void;
  isDone?: boolean;
}) {
  const hasAudio = Boolean(briefing.audio_base64);

  if (compact) {
    return (
      <div className="rounded-xl border border-india-green/25 bg-india-green/5 p-4">
        {hasAudio ? (
          <VoicePlayer
            audioBase64={briefing.audio_base64!}
            autoPlay={autoPlay}
            label="CA briefing"
            compact
          />
        ) : null}
        <p className="mt-2 text-sm text-slate-300">{briefing.briefing_text}</p>
      </div>
    );
  }

  return (
    <div className="ca-briefing-hero">
      <div className="ca-briefing-hero__glow" aria-hidden />

      <div className="relative z-10">
        <div className="flex flex-wrap items-center gap-2">
          <span className="ca-pill ca-pill--live">
            🎙 Aayan · {CA_VOICE_LANGUAGES.find((l) => l.code === briefing.voice_language)?.name || "Hindi"}
          </span>
          {editionLabel ? <span className="ca-pill">{editionLabel}</span> : null}
          {briefing.source ? <span className="ca-pill">{briefing.source}</span> : null}
          {isDone ? (
            <span className="ca-pill border-india-green/30 bg-india-green/10 text-india-green">
              ✓ Covered
            </span>
          ) : null}
        </div>

        <h2 className="mt-4 font-display text-2xl font-bold leading-snug text-white md:text-3xl">
          {briefing.article_title}
        </h2>

        {briefing.gs_link ? (
          <p className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-saffron/20 bg-saffron/5 px-3 py-1.5 text-xs text-saffron">
            <span aria-hidden>📚</span>
            Syllabus link: {briefing.gs_link}
          </p>
        ) : null}

        {briefing.source_url ? (
          <a
            href={briefing.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-flex items-center gap-1 text-sm text-slate-400 transition hover:text-saffron"
          >
            Read original article →
          </a>
        ) : null}

        {hasAudio ? (
          <VoicePlayer
            audioBase64={briefing.audio_base64!}
            autoPlay={autoPlay}
            label="Now playing"
            onPlaybackChange={onPlaybackChange}
          />
        ) : briefing.briefing_voice ? (
          <BrowserVoicePlayer
            speakText={briefing.briefing_voice}
            autoPlay={autoPlay}
            label="Now playing"
            lang={ttsCodeForVoice(briefing.voice_language || "hi")}
            onPlaybackChange={onPlaybackChange}
          />
        ) : (
          <p className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            {briefing.voice_error || "Voice is unavailable right now."}
          </p>
        )}

        <p className="mt-4 text-[10px] font-bold uppercase tracking-widest text-slate-500">
          For the exam
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {briefing.prelims_pointer ? (
            <InsightCard icon="🎯" label="Prelims" tone="emerald" text={briefing.prelims_pointer} />
          ) : null}
          {briefing.mains_angle ? (
            <InsightCard icon="✍️" label="Mains" tone="saffron" text={briefing.mains_angle} />
          ) : null}
          {briefing.interview_tip ? (
            <InsightCard icon="🎤" label="Interview" tone="teal" text={briefing.interview_tip} />
          ) : null}
        </div>

        {briefing.key_highlights?.length > 0 ? (
          <div className="mt-5 rounded-xl border border-white/[0.06] bg-black/20 p-4">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
              Quick revision
            </p>
            <ul className="mt-2 space-y-1.5">
              {briefing.key_highlights.slice(0, 3).map((h) => (
                <li key={h} className="flex gap-2 text-xs leading-relaxed text-slate-400">
                  <span className="text-india-green">•</span>
                  {h}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {briefing.briefing_text ? (
          <div className="mt-4 rounded-xl border border-white/[0.04] bg-white/[0.02] p-4">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
              One-line takeaway
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-300">{briefing.briefing_text}</p>
          </div>
        ) : null}

        {hasNext && onNextStory ? (
          <button type="button" onClick={onNextStory} className="next-story-cta">
            Next story
            <span aria-hidden>→</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

function InsightCard({
  icon,
  label,
  text,
  tone,
}: {
  icon: string;
  label: string;
  text: string;
  tone: "emerald" | "saffron" | "teal";
}) {
  const toneClass =
    tone === "emerald"
      ? "border-emerald-500/25 bg-emerald-500/10"
      : tone === "saffron"
        ? "border-saffron/25 bg-saffron/10"
        : "border-india-green/25 bg-india-green/10";
  const labelClass =
    tone === "emerald"
      ? "text-emerald-300"
      : tone === "saffron"
        ? "text-saffron"
        : "text-india-green";

  return (
    <div className={`rounded-xl border p-4 ${toneClass}`}>
      <p className={`flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest ${labelClass}`}>
        <span aria-hidden>{icon}</span>
        {label}
      </p>
      <p className="mt-2 text-xs leading-relaxed text-slate-300">{text}</p>
    </div>
  );
}
