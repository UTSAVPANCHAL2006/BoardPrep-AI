"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  formatAudioTime,
  getStableAudio,
  type AudioPlaybackState,
} from "@/lib/audio";
import { Waveform } from "./Waveform";

const SPEED_OPTIONS = [0.85, 1, 1.15] as const;

function deriveState(audio: HTMLAudioElement): AudioPlaybackState {
  if (!audio.paused) return "playing";
  if (audio.currentTime > 0 && (!Number.isFinite(audio.duration) || audio.currentTime < audio.duration)) {
    return "paused";
  }
  return "idle";
}

export function VoicePlayer({
  audioBase64,
  autoPlay = false,
  label = "Voice briefing",
  compact = false,
  onPlaybackChange,
}: {
  audioBase64: string;
  autoPlay?: boolean;
  label?: string;
  compact?: boolean;
  onPlaybackChange?: (state: AudioPlaybackState) => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const speedRef = useRef(1);
  const onPlaybackChangeRef = useRef(onPlaybackChange);
  const [state, setState] = useState<AudioPlaybackState>("idle");
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState<number>(1);
  const autoPlayedRef = useRef(false);

  onPlaybackChangeRef.current = onPlaybackChange;

  const updateState = useCallback((next: AudioPlaybackState) => {
    setState(next);
    onPlaybackChangeRef.current?.(next);
  }, []);

  const syncTime = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    setCurrent(audio.currentTime);
    if (Number.isFinite(audio.duration)) {
      setDuration(audio.duration);
    }
  }, []);

  useEffect(() => {
    if (!audioBase64) return;

    const audio = getStableAudio(audioBase64);
    audio.playbackRate = speedRef.current;
    audioRef.current = audio;
    autoPlayedRef.current = false;

    updateState(deriveState(audio));
    setCurrent(audio.currentTime);
    if (Number.isFinite(audio.duration)) setDuration(audio.duration);

    const onPlay = () => updateState("playing");
    const onPause = () => updateState(deriveState(audio));
    const onEnded = () => {
      updateState("idle");
      setCurrent(0);
    };
    const onTimeUpdate = () => syncTime();
    const onLoaded = () => {
      if (Number.isFinite(audio.duration)) setDuration(audio.duration);
    };

    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("loadedmetadata", onLoaded);

    return () => {
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("loadedmetadata", onLoaded);
    };
  }, [audioBase64, syncTime, updateState]);

  useEffect(() => {
    if (!autoPlay || !audioRef.current || autoPlayedRef.current) return;
    autoPlayedRef.current = true;
    void audioRef.current.play().catch(() => updateState("idle"));
  }, [autoPlay, audioBase64, updateState]);

  async function onStart() {
    const audio = audioRef.current;
    if (!audio) return;
    try {
      if (state === "paused") {
        await audio.play();
      } else {
        audio.currentTime = 0;
        await audio.play();
      }
    } catch {
      updateState("idle");
    }
  }

  function onPauseClick() {
    const audio = audioRef.current;
    if (!audio || audio.paused) return;
    audio.pause();
    updateState("paused");
  }

  function onStop() {
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    audio.currentTime = 0;
    setCurrent(0);
    updateState("idle");
  }

  const pct = duration > 0 ? Math.min(100, (current / duration) * 100) : 0;
  const isActive = state === "playing" || state === "paused";

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <PlayerButton
          icon={state === "playing" ? "pause" : "play"}
          title={state === "playing" ? "Pause" : "Play"}
          onClick={() => (state === "playing" ? onPauseClick() : void onStart())}
        />
        <PlayerButton icon="stop" title="Stop" onClick={onStop} disabled={!isActive} />
      </div>
    );
  }

  return (
    <div className="voice-player-shell">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Waveform active={state === "playing"} />
          <p className="text-[10px] font-semibold uppercase tracking-widest text-india-green">{label}</p>
        </div>
        <div className="flex gap-1">
          {SPEED_OPTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => {
                speedRef.current = s;
                setSpeed(s);
                if (audioRef.current) audioRef.current.playbackRate = s;
              }}
              className={`rounded px-1.5 py-0.5 text-[10px] tabular-nums transition ${
                speed === s
                  ? "bg-saffron/20 text-saffron ring-1 ring-saffron/40"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <PlayerButton
          icon={state === "playing" ? "pause" : "play"}
          title={state === "playing" ? "Pause" : state === "paused" ? "Resume" : "Start"}
          onClick={() => (state === "playing" ? onPauseClick() : void onStart())}
          primary
          large
        />
        <PlayerButton icon="stop" title="Stop" onClick={onStop} disabled={!isActive} />
        <span className="ml-auto text-xs tabular-nums text-slate-400">
          {formatAudioTime(current)} / {formatAudioTime(duration)}
        </span>
      </div>

      <div className="voice-progress-track mt-3">
        <div className="voice-progress-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function PlayerButton({
  icon,
  title,
  onClick,
  disabled = false,
  primary = false,
  large = false,
}: {
  icon: "play" | "pause" | "stop";
  title: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  large?: boolean;
}) {
  const size = large ? "h-12 w-12" : "h-10 w-10";
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`flex ${size} items-center justify-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-40 ${
        primary
          ? "bg-gradient-to-br from-saffron to-saffron-light text-navy-deep shadow-glow hover:brightness-110"
          : "bg-white/5 text-slate-300 ring-1 ring-white/10 hover:bg-white/10"
      }`}
    >
      {icon === "play" && (
        <svg className="h-5 w-5 translate-x-0.5" fill="currentColor" viewBox="0 0 24 24">
          <path d="M8 5v14l11-7z" />
        </svg>
      )}
      {icon === "pause" && (
        <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
          <path d="M6 5h4v14H6V5zm8 0h4v14h-4V5z" />
        </svg>
      )}
      {icon === "stop" && (
        <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
          <path d="M6 6h12v12H6V6z" />
        </svg>
      )}
    </button>
  );
}
