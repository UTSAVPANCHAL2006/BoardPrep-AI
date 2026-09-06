"use client";

import { useEffect, useRef, useState } from "react";
import type { AudioPlaybackState } from "@/lib/audio";
import {
  browserTtsSupported,
  pauseBrowserTts,
  resumeBrowserTts,
  speakBrowserTts,
  stopBrowserTts,
} from "@/lib/browser-tts";

export function BrowserVoicePlayer({
  speakText,
  autoPlay = false,
  label = "Voice briefing",
  lang = "hi-IN",
  onPlaybackChange,
}: {
  speakText: string;
  autoPlay?: boolean;
  label?: string;
  lang?: string;
  onPlaybackChange?: (state: AudioPlaybackState) => void;
}) {
  const [state, setState] = useState<AudioPlaybackState>("idle");
  const autoPlayedRef = useRef(false);

  function setPlayback(next: AudioPlaybackState) {
    setState(next);
    onPlaybackChange?.(next);
  }

  useEffect(() => {
    return () => stopBrowserTts();
  }, []);

  useEffect(() => {
    autoPlayedRef.current = false;
    setPlayback("idle");
  }, [speakText]);

  useEffect(() => {
    if (!autoPlay || autoPlayedRef.current || !speakText) return;
    autoPlayedRef.current = true;
    speakBrowserTts(speakText, setPlayback, 0.95, lang);
  }, [autoPlay, speakText, lang]);

  if (!browserTtsSupported()) {
    return (
      <p className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
        Browser voice not supported on this device.
      </p>
    );
  }

  return (
    <div className="voice-player-shell">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-india-green">
        {label} · browser mode
      </p>
      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={() => {
            if (state === "playing") {
              pauseBrowserTts();
              setPlayback("paused");
            } else if (state === "paused") {
              resumeBrowserTts();
              setPlayback("playing");
            } else {
              speakBrowserTts(speakText, setPlayback, 0.95, lang);
            }
          }}
          className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-saffron to-saffron-light text-navy-deep shadow-glow"
        >
          {state === "playing" ? "⏸" : "▶"}
        </button>
        <button
          type="button"
          onClick={() => {
            stopBrowserTts();
            setPlayback("idle");
          }}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-white/5 text-slate-300 ring-1 ring-white/10"
        >
          ■
        </button>
        <span className="ml-auto text-xs text-slate-500">
          {state === "playing" ? "Speaking…" : state === "paused" ? "Paused" : "Ready"}
        </span>
      </div>
    </div>
  );
}
