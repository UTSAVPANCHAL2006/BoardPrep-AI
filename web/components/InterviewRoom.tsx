"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  createStreamingAudioQueue,
  respondStream,
  startInterview,
  getSupportedAudioMimeType,
  stopStreamingAudio,
} from "@/lib/api";
import type { CABriefing, CASource, DAFFlag, RetrievedChunk } from "@/lib/types";
import { attachSilenceAutoStop, startLiveCaption } from "@/lib/voice-vad";
import { CaBriefingCard } from "./CaBriefingCard";
import { VoicePlayer } from "./VoicePlayer";
import { DafFlagsBanner } from "./DafFlagsBanner";
import { MicButton } from "./MicButton";
import { PhaseStepper } from "./PhaseStepper";
import { RetrievalSidebar } from "./RetrievalSidebar";

interface Turn {
  role: "panel" | "candidate";
  content: string;
}

const PHASE_LABELS: Record<string, string> = {
  daf_opening: "DAF Opening",
  subject_probe: "Subject Probe",
  current_affairs: "Current Affairs",
  closing: "Closing Round",
};

export function InterviewRoom({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const devMode = searchParams.get("dev") === "1";

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [phase, setPhase] = useState("daf_opening");
  const [question, setQuestion] = useState("");
  const [dafFocus, setDafFocus] = useState("");
  const [chunks, setChunks] = useState<RetrievedChunk[]>([]);
  const [caSource, setCaSource] = useState<CASource | null>(null);
  const [caBriefing, setCaBriefing] = useState<CABriefing | null>(null);
  const [dafFlags, setDafFlags] = useState<DAFFlag[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [textAnswer, setTextAnswer] = useState("");
  const [recording, setRecording] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [lastAudio, setLastAudio] = useState("");
  const [boardStreaming, setBoardStreaming] = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  const [liveCaption, setLiveCaption] = useState("");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mimeTypeRef = useRef("audio/webm");
  const vadCleanupRef = useRef<(() => void) | null>(null);
  const captionCleanupRef = useRef<(() => void) | null>(null);
  const autoStopRef = useRef(false);

  function cleanupRecordingExtras() {
    vadCleanupRef.current?.();
    vadCleanupRef.current = null;
    captionCleanupRef.current?.();
    captionCleanupRef.current = null;
  }

  useEffect(() => () => cleanupRecordingExtras(), []);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const res = await startInterview(sessionId);
        if (cancelled) return;
        setPhase(res.current_phase);
        setQuestion(res.question);
        setDafFocus(res.daf_focus || "");
        setChunks(res.retrieved_chunks);
        setCaSource(res.ca_source ?? null);
        setCaBriefing(res.ca_briefing ?? null);
        setTurns([{ role: "panel", content: res.question }]);
        setLastAudio(res.audio_base64);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to start");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  async function handleRespond(blob?: Blob, mimeType?: string, text?: string) {
    setBusy(true);
    setError("");
    stopStreamingAudio();
    const audioQueue = createStreamingAudioQueue();
    setLastAudio("");
    setBoardStreaming(true);
    let interviewComplete = false;
    try {
      await respondStream(
        sessionId,
        blob,
        text,
        mimeType || mimeTypeRef.current,
        (meta) => {
          setTurns((prev) => [
            ...prev,
            { role: "candidate", content: meta.transcript },
            ...(meta.question ? [{ role: "panel" as const, content: meta.question }] : []),
          ]);
          setPhase(meta.current_phase);
          setQuestion(meta.question);
          setDafFocus(meta.daf_focus || "");
          setChunks(meta.retrieved_chunks);
          setCaSource(meta.ca_source ?? null);
          setCaBriefing(meta.ca_briefing ?? null);
          setDafFlags(meta.daf_flags);
          setTextAnswer("");
          if (meta.interview_complete) {
            interviewComplete = true;
            audioQueue.stop();
            stopStreamingAudio();
            setBoardStreaming(false);
            setLastAudio("");
            router.push(`/feedback?session=${sessionId}`);
          }
        },
        (chunk) => {
          if (interviewComplete) return;
          void audioQueue.enqueue(chunk.audio_base64);
        },
        undefined,
        (audioBase64) => {
          if (interviewComplete) return;
          setLastAudio(audioBase64);
        }
      );
      if (!interviewComplete) {
        await audioQueue.waitUntilIdle();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit");
    } finally {
      setBoardStreaming(false);
      setBusy(false);
    }
  }

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = getSupportedAudioMimeType();
      mimeTypeRef.current = mimeType;
      autoStopRef.current = false;
      setLiveCaption("");
      const recorder = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = () => {
        cleanupRecordingExtras();
        stream.getTracks().forEach((t) => t.stop());
        const type = recorder.mimeType || mimeType;
        const blob = new Blob(chunksRef.current, { type });
        if (blob.size < 1000) {
          setError("Recording too short — please speak for at least 2 seconds.");
          return;
        }
        void handleRespond(blob, type);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      vadCleanupRef.current = attachSilenceAutoStop(stream, () => {
        if (!autoStopRef.current && mediaRecorderRef.current?.state === "recording") {
          autoStopRef.current = true;
          stopRecording();
        }
      });
      captionCleanupRef.current = startLiveCaption((text) => {
        setLiveCaption(text);
      });
      setRecording(true);
      setError("");
    } catch {
      setError("Microphone access denied. Please allow mic permission and try again.");
    }
  }

  function stopRecording() {
    cleanupRecordingExtras();
    mediaRecorderRef.current?.stop();
    setRecording(false);
    setLiveCaption("");
  }

  if (loading) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6">
        <div className="relative">
          <div className="h-20 w-20 animate-spin rounded-full border-2 border-saffron/20 border-t-saffron" />
          <div className="absolute inset-0 flex items-center justify-center text-2xl">🏛️</div>
        </div>
        <div className="text-center">
          <p className="font-display text-xl font-semibold">Preparing the Board Room</p>
          <p className="mt-2 text-sm text-slate-500">Indexing syllabus, fetching current affairs, reading your DAF...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PhaseStepper currentPhase={phase} />

      <div className={`grid gap-5 ${sidebarOpen ? "lg:grid-cols-[1fr_300px]" : ""}`}>
        <div className="space-y-4">
          <div className="gradient-border animate-fade-up">
            <div className="inner space-y-6 p-6 md:p-8">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="relative">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-navy-border to-navy text-xl shadow-lg">
                      👤
                    </div>
                    <span className="absolute -bottom-0.5 -right-0.5 h-3.5 w-3.5 rounded-full border-2 border-navy-card bg-emerald-400" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-200">UPSC Board Member</p>
                    <p className="text-xs text-saffron/80">{PHASE_LABELS[phase] || phase}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="btn-icon"
                    onClick={() => setSidebarOpen((o) => !o)}
                    title="Toggle context panel"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
                    </svg>
                  </button>
                </div>
              </div>

              <DafFlagsBanner flags={dafFlags} />

              {phase === "current_affairs" && caBriefing && (
                <CaBriefingCard briefing={{ ...caBriefing, audio_base64: "" }} compact autoPlay={false} />
              )}

              <div className="relative pl-4">
                <div className="absolute left-0 top-0 h-full w-1 rounded-full bg-gradient-to-b from-saffron to-saffron-dark" />
                <p className="question-text">&ldquo;{question}&rdquo;</p>
              </div>

              {boardStreaming && (
                <p className="text-xs font-medium uppercase tracking-widest text-saffron/90">
                  Board speaking — streaming voice
                </p>
              )}

              {lastAudio && !boardStreaming && (
                <VoicePlayer
                  audioBase64={lastAudio}
                  label="Board question voice"
                  autoPlay={false}
                />
              )}

              <div className="flex items-center gap-4">
                <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/10 to-transparent" />
                <span className="text-xs uppercase tracking-widest text-slate-600">Your turn</span>
                <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/10 to-transparent" />
              </div>

              <MicButton
                recording={recording}
                busy={busy}
                liveCaption={liveCaption}
                onStart={() => void startRecording()}
                onStop={stopRecording}
              />
            </div>
          </div>

          {devMode && (
            <div className="glass-card space-y-3 border-dashed !border-amber-500/30">
              <p className="text-xs font-semibold uppercase tracking-widest text-amber-400">Dev mode</p>
              <textarea
                value={textAnswer}
                onChange={(e) => setTextAnswer(e.target.value)}
                rows={3}
                placeholder="Type answer instead of speaking..."
                className="w-full rounded-xl border border-white/10 bg-navy-deep/60 p-3 text-sm focus:border-saffron/40 focus:outline-none"
              />
              <button
                type="button"
                className="btn-ghost"
                disabled={busy || !textAnswer.trim()}
                onClick={() => void handleRespond(undefined, undefined, textAnswer)}
              >
                Submit text answer
              </button>
            </div>
          )}

          {error && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-center text-sm text-red-300">
              {error}
            </div>
          )}

          {turns.length > 1 && (
            <div className="glass-card">
              <button
                type="button"
                onClick={() => setShowTranscript((s) => !s)}
                className="flex w-full items-center justify-between text-sm text-slate-400 hover:text-slate-200"
              >
                <span>Conversation transcript ({turns.length} messages)</span>
                <span>{showTranscript ? "▲" : "▼"}</span>
              </button>
              {showTranscript && (
                <div className="mt-4 max-h-64 space-y-3 overflow-y-auto">
                  {turns.map((t, i) => (
                    <div
                      key={i}
                      className={`flex ${t.role === "candidate" ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                          t.role === "panel"
                            ? "rounded-tl-sm bg-saffron/15 text-slate-100"
                            : "rounded-tr-sm bg-white/10 text-slate-300"
                        }`}
                      >
                        <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider opacity-50">
                          {t.role === "panel" ? "Board" : "You"}
                        </p>
                        {t.content}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {sidebarOpen && (
          <RetrievalSidebar chunks={chunks} caSource={caSource} dafFocus={dafFocus} phase={phase} />
        )}
      </div>
    </div>
  );
}
