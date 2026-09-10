import type {
  CABriefing,
  DailyCAResponse,
  FeedbackReportResponse,
  InterviewMode,
  RespondResponse,
  StartInterviewResponse,
  UploadDAFResponse,
} from "./types";
import {
  createAudioFromBase64,
  pauseStableAudio,
  playEphemeralAudioAndWait,
  playStableAudioAndWait,
  releaseStableAudio,
} from "@/lib/audio";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const UPLOAD_TIMEOUT_MS = 60_000;
const START_INTERVIEW_TIMEOUT_MS = 120_000;
const RESPOND_TIMEOUT_MS = 180_000;

export type StreamAudioChunk = {
  index: number;
  total: number;
  text: string;
  audio_base64: string;
};

export type StreamRespondMetadata = Pick<
  RespondResponse,
  | "session_id"
  | "transcript"
  | "question"
  | "current_phase"
  | "interview_complete"
  | "router_action"
  | "daf_flags"
  | "daf_focus"
  | "retrieved_chunks"
  | "ca_source"
  | "ca_briefing"
  | "evaluation_notes"
  | "evaluation"
>;

class StreamingAudioQueue {
  private queue: string[] = [];
  private playing = false;
  private stopped = false;
  private idleWaiters: Array<() => void> = [];

  enqueue(base64: string): void {
    if (!base64 || this.stopped) return;
    this.queue.push(base64);
    void this.drain();
  }

  waitUntilIdle(): Promise<void> {
    if (!this.playing && this.queue.length === 0) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      this.idleWaiters.push(resolve);
    });
  }

  private notifyIdle(): void {
    if (!this.playing && this.queue.length === 0) {
      const waiters = this.idleWaiters.splice(0);
      waiters.forEach((resolve) => resolve());
    }
  }

  private async drain(): Promise<void> {
    if (this.playing || this.stopped) return;
    this.playing = true;
    while (this.queue.length && !this.stopped) {
      const chunk = this.queue.shift();
      if (!chunk) break;
      await playEphemeralAudioAndWait(chunk);
    }
    this.playing = false;
    this.notifyIdle();
    if (this.queue.length && !this.stopped) {
      void this.drain();
    }
  }

  stop(): void {
    this.stopped = true;
    this.queue = [];
    this.playing = false;
    stopAudio();
  }

  reset(): void {
    this.stopped = false;
    this.queue = [];
    this.playing = false;
  }
}

let streamingQueue: StreamingAudioQueue | null = null;

export function createStreamingAudioQueue(): StreamingAudioQueue {
  streamingQueue?.stop();
  streamingQueue = new StreamingAudioQueue();
  return streamingQueue;
}

export function stopStreamingAudio(): void {
  streamingQueue?.stop();
  streamingQueue = null;
}

let activeAudio: HTMLAudioElement | null = null;

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try {
      const json = await res.json();
      detail = json.detail || JSON.stringify(json);
    } catch {
      detail = await res.text();
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

async function apiFetch(url: string, options: RequestInit, timeoutMs = 20000): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(
        "Request timed out — STT, board evaluation, and voice can take 1–3 minutes. Please wait and try again."
      );
    }
    throw new Error(
      "Cannot reach the server. Make sure the backend is running on port 8000."
    );
  } finally {
    clearTimeout(timer);
  }
}

const startInterviewInflight = new Map<string, Promise<StartInterviewResponse>>();

export async function uploadDaf(
  file: File,
  interviewMode: InterviewMode = "full"
): Promise<UploadDAFResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("interview_mode", interviewMode);
  const res = await apiFetch(`${API_URL}/upload-daf`, { method: "POST", body: form }, UPLOAD_TIMEOUT_MS);
  return handleResponse<UploadDAFResponse>(res);
}

export async function startInterview(sessionId: string): Promise<StartInterviewResponse> {
  const pending = startInterviewInflight.get(sessionId);
  if (pending) return pending;

  const form = new FormData();
  form.append("session_id", sessionId);
  const task = apiFetch(`${API_URL}/start-interview`, { method: "POST", body: form }, START_INTERVIEW_TIMEOUT_MS)
    .then((res) => handleResponse<StartInterviewResponse>(res))
    .finally(() => {
      startInterviewInflight.delete(sessionId);
    });
  startInterviewInflight.set(sessionId, task);
  return task;
}

function extForMime(mime: string): string {
  if (mime.includes("webm")) return "webm";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4")) return "m4a";
  return "wav";
}

export async function respondWithAudio(
  sessionId: string,
  audioBlob: Blob,
  mimeType = "audio/webm"
): Promise<RespondResponse> {
  const form = new FormData();
  form.append("session_id", sessionId);
  const ext = extForMime(mimeType);
  form.append("audio", audioBlob, `answer.${ext}`);
  const res = await apiFetch(`${API_URL}/respond`, { method: "POST", body: form }, RESPOND_TIMEOUT_MS);
  return handleResponse<RespondResponse>(res);
}

export async function respondWithText(
  sessionId: string,
  textAnswer: string
): Promise<RespondResponse> {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("text_answer", textAnswer);
  const res = await apiFetch(`${API_URL}/respond`, { method: "POST", body: form }, RESPOND_TIMEOUT_MS);
  return handleResponse<RespondResponse>(res);
}

export async function respondStream(
  sessionId: string,
  audioBlob?: Blob,
  textAnswer?: string,
  mimeType = "audio/webm",
  onMetadata?: (meta: StreamRespondMetadata) => void,
  onAudioChunk?: (chunk: StreamAudioChunk) => void,
  onBriefingAudio?: (audioBase64: string) => void,
  onQuestionAudio?: (audioBase64: string) => void
): Promise<void> {
  const form = new FormData();
  form.append("session_id", sessionId);
  if (textAnswer) {
    form.append("text_answer", textAnswer);
  } else if (audioBlob) {
    const ext = extForMime(mimeType);
    form.append("audio", audioBlob, `answer.${ext}`);
  } else {
    throw new Error("Provide audio or text_answer");
  }

  const res = await apiFetch(`${API_URL}/respond-stream`, { method: "POST", body: form }, RESPOND_TIMEOUT_MS);

  if (!res.ok || !res.body) {
    throw new Error(`Streaming failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payloadStr = line.replace(/^data:\s*/, "").trim();
      if (payloadStr === "[DONE]") return;
      try {
        const payload = JSON.parse(payloadStr);
        if (payload.type === "metadata" && onMetadata) {
          onMetadata(payload as StreamRespondMetadata);
        } else if (payload.type === "briefing_audio" && onBriefingAudio && payload.audio_base64) {
          onBriefingAudio(payload.audio_base64);
        } else if (payload.type === "audio_chunk" && onAudioChunk) {
          onAudioChunk(payload as StreamAudioChunk);
        } else if (payload.type === "question_audio" && onQuestionAudio && payload.audio_base64) {
          onQuestionAudio(payload.audio_base64);
        }
      } catch {
        // ignore parse errors on partial chunk lines
      }
    }
  }
}

export async function fetchFeedbackReport(sessionId: string): Promise<FeedbackReportResponse> {
  const res = await apiFetch(`${API_URL}/feedback-report/${sessionId}`, {});
  return handleResponse<FeedbackReportResponse>(res);
}

export function stopAudio(): void {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio.currentTime = 0;
    activeAudio = null;
  }
  releaseStableAudio();
}

export function pauseAudio(): void {
  activeAudio?.pause();
  pauseStableAudio();
}

export async function resumeAudio(): Promise<boolean> {
  if (!activeAudio) return false;
  try {
    await activeAudio.play();
    return true;
  } catch {
    return false;
  }
}

/** Returns true if playback started. Browsers often block autoplay after async delays. */
export async function playBase64Audio(base64: string): Promise<boolean> {
  if (!base64) return false;
  stopAudio();
  activeAudio = createAudioFromBase64(base64);
  activeAudio.onended = () => {
    activeAudio = null;
  };
  try {
    await activeAudio.play();
    return true;
  } catch {
    activeAudio = null;
    return false;
  }
}

export function waitForActiveAudioEnd(): Promise<void> {
  return new Promise((resolve) => {
    if (!activeAudio) {
      resolve();
      return;
    }
    const audio = activeAudio;
    const done = () => {
      if (activeAudio === audio) activeAudio = null;
      resolve();
    };
    audio.onended = done;
    audio.onerror = done;
  });
}

/** Auto-speak a board question once; returns false if the browser blocked autoplay. */
export async function playBoardQuestionAudio(base64: string): Promise<boolean> {
  if (!base64) return false;
  stopStreamingAudio();
  const started = await playBase64Audio(base64);
  if (!started) return false;
  await waitForActiveAudioEnd();
  return true;
}

export function playBase64Wav(base64: string): void {
  void playBase64Audio(base64);
}

export function playBase64AudioAndWait(base64: string): Promise<void> {
  return playStableAudioAndWait(base64);
}

export function playAudioSequence(base64List: string[]): Promise<void> {
  const clips = base64List.filter(Boolean);
  if (!clips.length) return Promise.resolve();

  return clips.reduce(
    (chain, b64) =>
      chain.then(async () => {
        const ok = await playBase64Audio(b64);
        if (!ok) return;
        await new Promise<void>((resolve) => {
          if (!activeAudio) {
            resolve();
            return;
          }
          activeAudio.onended = () => {
            activeAudio = null;
            resolve();
          };
          activeAudio.onerror = () => resolve();
        });
      }),
    Promise.resolve()
  );
}

export async function fetchDailyCA(sessionId?: string): Promise<DailyCAResponse> {
  const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const res = await apiFetch(`${API_URL}/current-affairs/daily${q}`, {}, 30000);
  return handleResponse<DailyCAResponse>(res);
}

export async function fetchCachedBriefing(
  articleIndex: number,
  language?: string
): Promise<CABriefing | null> {
  const q = new URLSearchParams({
    article_index: String(articleIndex),
    language: language || "hi",
  });
  const res = await apiFetch(`${API_URL}/current-affairs/explain-cached?${q}`, {}, 15000);
  if (res.status === 404) return null;
  return handleResponse<CABriefing>(res);
}

export async function prewarmCaAudio(language?: string): Promise<void> {
  const form = new FormData();
  if (language) form.append("language", language);
  await apiFetch(`${API_URL}/current-affairs/prewarm`, { method: "POST", body: form }, 120000);
}

export async function explainCurrentAffair(
  articleIndex: number,
  sessionId?: string,
  language?: string
): Promise<CABriefing> {
  const form = new FormData();
  form.append("article_index", String(articleIndex));
  if (sessionId) form.append("session_id", sessionId);
  if (language) form.append("language", language);
  const res = await apiFetch(`${API_URL}/current-affairs/explain`, { method: "POST", body: form }, 180000);
  return handleResponse<CABriefing>(res);
}

export function getSupportedAudioMimeType(): string {
  const types = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "audio/ogg",
  ];
  for (const t of types) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) {
      return t;
    }
  }
  return "audio/webm";
}
