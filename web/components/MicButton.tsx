"use client";

import { Waveform } from "./Waveform";

export function MicButton({
  recording,
  busy,
  boardSpeaking,
  liveCaption,
  autoSubmitInSec,
  onStart,
  onStop,
}: {
  recording: boolean;
  busy: boolean;
  boardSpeaking?: boolean;
  liveCaption?: string;
  autoSubmitInSec?: number | null;
  onStart: () => void;
  onStop: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-5">
      {/* Outer rings */}
      <div className="relative">
        {(recording || busy) && (
          <>
            <span className="absolute inset-0 -m-4 animate-pulse-ring rounded-full border border-saffron/30" />
            <span className="absolute inset-0 -m-8 animate-pulse-ring rounded-full border border-saffron/15" style={{ animationDelay: "0.5s" }} />
          </>
        )}

        <button
          type="button"
          disabled={busy || boardSpeaking}
          onClick={recording ? onStop : onStart}
          className={`relative z-10 flex h-28 w-28 items-center justify-center rounded-full transition-all duration-300 disabled:opacity-50 ${
            recording
              ? "bg-gradient-to-br from-red-500 to-red-600 shadow-[0_0_40px_rgba(239,68,68,0.4)]"
              : busy
                ? "bg-navy-border"
                : "bg-gradient-to-br from-saffron to-saffron-dark shadow-glow-lg hover:scale-105 hover:shadow-glow"
          }`}
          aria-label={recording ? "Stop recording" : "Start recording"}
        >
          {busy ? (
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-saffron border-t-transparent" />
          ) : (
            <svg className="h-11 w-11 text-navy" fill="currentColor" viewBox="0 0 24 24">
              {recording ? (
                <rect x="6" y="6" width="12" height="12" rx="2" fill="white" />
              ) : (
                <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z" />
              )}
            </svg>
          )}
        </button>
      </div>

      <Waveform active={recording} />

      <div className="text-center">
        <p className="text-sm font-medium text-slate-200">
          {boardSpeaking
            ? "Board bol raha hai — khatam hone ke baad mic khulega"
            : busy
            ? "Transcribing & evaluating — can take 1–2 min"
            : recording
              ? autoSubmitInSec
                ? `Chup ho gaye — ${autoSubmitInSec}s mein auto-submit`
                : "Sun raha hoon — boliye, ~7 sec pause pe submit"
              : "Tap microphone to respond"}
        </p>
        {recording && liveCaption && (
          <p className="mt-2 max-w-md text-sm italic text-saffron/90">
            Live: &ldquo;{liveCaption}&rdquo;
          </p>
        )}
        {recording && !liveCaption && (
          <p className="mt-2 text-xs text-slate-500">
            Auto-submit ~7 sec silence ke baad · tap se turant bhejo
          </p>
        )}
        <p className="mt-1 text-xs text-slate-500">
          {boardSpeaking
            ? "Question sun lijiye, phir record kijiye"
            : busy
            ? "STT → board LLM → next question voice"
            : recording
              ? "Sochne ka gap chalega — pause pe countdown dikhega"
              : "Speak clearly in Hindi or English"}
        </p>
      </div>
    </div>
  );
}
