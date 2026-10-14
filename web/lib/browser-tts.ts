// Browser text-to-speech fallback.

import type { AudioPlaybackState } from "@/lib/audio";

export function browserTtsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function stopBrowserTts(): void {
  if (typeof window === "undefined") return;
  window.speechSynthesis.cancel();
}

export function speakBrowserTts(
  text: string,
  onState?: (state: AudioPlaybackState) => void,
  rate = 0.95,
  lang = "hi-IN"
): boolean {
  if (!browserTtsSupported() || !text.trim()) return false;
  stopBrowserTts();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = rate;
  const voices = window.speechSynthesis.getVoices();
  const prefix = lang.slice(0, 2).toLowerCase();
  const match =
    voices.find((v) => v.lang.toLowerCase().startsWith(prefix)) ||
    voices.find((v) => v.lang.toLowerCase() === lang.toLowerCase());
  if (match) utterance.voice = match;

  utterance.onstart = () => onState?.("playing");
  utterance.onpause = () => onState?.("paused");
  utterance.onend = () => {
    onState?.("idle");
  };
  utterance.onerror = () => {
    onState?.("idle");
  };

  window.speechSynthesis.speak(utterance);
  return true;
}

export function pauseBrowserTts(): void {
  window.speechSynthesis.pause();
}

export function resumeBrowserTts(): void {
  window.speechSynthesis.resume();
}
