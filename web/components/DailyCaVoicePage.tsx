"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { explainCurrentAffair, fetchCachedBriefing, fetchDailyCA, playBase64AudioAndWait, prewarmCaAudio, stopAudio } from "@/lib/api";
import type { AudioPlaybackState } from "@/lib/audio";
import {
  getStudyStreak,
  loadDailyProgress,
  markStoryListened,
  type DailyProgress,
} from "@/lib/study-progress";
import type { CABriefing, EnrichedArticle } from "@/lib/types";
import {
  CA_VOICE_LANGUAGES,
  DEFAULT_CA_VOICE_LANG,
  loadVoiceLanguage,
  saveVoiceLanguage,
  type CaVoiceLangCode,
} from "@/lib/voice-language";
import { CaArticleDetail, GsTag } from "./CaArticleDetail";
import { CaBriefingCard } from "./CaBriefingCard";
import { StudyProgressBar } from "./StudyProgressBar";
import { StudyTipBanner } from "./StudyTipBanner";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export function DailyCaVoicePage() {
  const [articles, setArticles] = useState<EnrichedArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editionDate, setEditionDate] = useState("");
  const [isLive, setIsLive] = useState(false);
  const [isFallback, setIsFallback] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);
  const [busyIndex, setBusyIndex] = useState<number | null>(null);
  const [activeBriefing, setActiveBriefing] = useState<CABriefing | null>(null);
  const [activeArticleIndex, setActiveArticleIndex] = useState<number | null>(null);
  const [readIndex, setReadIndex] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [autoPlayBriefing, setAutoPlayBriefing] = useState(false);
  const [playlistRunning, setPlaylistRunning] = useState(false);
  const [playlistProgress, setPlaylistProgress] = useState("");
  const [playbackState, setPlaybackState] = useState<AudioPlaybackState>("idle");
  const [studyProgress, setStudyProgress] = useState<DailyProgress | null>(null);
  const [streak, setStreak] = useState(0);
  const [voiceLang, setVoiceLang] = useState<CaVoiceLangCode>(DEFAULT_CA_VOICE_LANG);
  const [voicesReady, setVoicesReady] = useState(0);
  const [voiceReadyIndexes, setVoiceReadyIndexes] = useState<Set<number>>(() => new Set());
  const playlistCancelRef = useRef(false);
  const isPlayingRef = useRef(false);
  const wasPlayingRef = useRef(false);
  const briefingCacheRef = useRef<Map<string, CABriefing>>(new Map());

  const briefingCacheKey = useCallback(
    (index: number, lang: CaVoiceLangCode = voiceLang) => `${lang}:${index}`,
    [voiceLang]
  );

  const markVoiceReady = useCallback((index: number, briefing: CABriefing) => {
    briefingCacheRef.current.set(briefingCacheKey(index), briefing);
    setVoiceReadyIndexes((prev) => {
      if (prev.has(index)) return prev;
      const next = new Set(prev);
      next.add(index);
      return next;
    });
  }, [briefingCacheKey]);

  const warmVoiceCache = useCallback(async (indexes: number[]) => {
    await Promise.all(
      indexes.map(async (index) => {
        if (briefingCacheRef.current.has(briefingCacheKey(index))) return;
        const hit = await fetchCachedBriefing(index, voiceLang);
        if (hit?.audio_base64) markVoiceReady(index, hit);
      })
    );
  }, [briefingCacheKey, markVoiceReady, voiceLang]);

  const loadDaily = useCallback(async (silent = false) => {
    if (isPlayingRef.current) return { is_live: false, is_preparing: false };
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const res = await fetchDailyCA();
      setArticles((prev) => {
        if (
          prev.length === res.articles.length &&
          prev.every((a, i) => a.title === res.articles[i]?.title)
        ) {
          return prev;
        }
        return res.articles;
      });
      setEditionDate(res.edition_date);
      setIsLive(res.is_live);
      setIsFallback(Boolean(res.is_fallback));
      setIsPreparing(Boolean(res.is_preparing));
      setVoicesReady(res.voices_ready ?? 0);
      setError("");
      if (res.articles.length) {
        void warmVoiceCache([0, 1, 2].filter((i) => i < res.articles.length));
      }
      return { is_live: res.is_live, is_preparing: Boolean(res.is_preparing) };
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load current affairs");
      return { is_live: false, is_preparing: false };
    } finally {
      if (!silent) setLoading(false);
      setRefreshing(false);
    }
  }, [warmVoiceCache]);

  useEffect(() => {
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;

    async function init() {
      const silent = attempts > 0;
      const result = await loadDaily(silent);
      if (cancelled || isPlayingRef.current) return;
      const shouldPoll = result.is_preparing && !result.is_live && attempts < 18;
      if (shouldPoll) {
        attempts += 1;
        pollTimer = setTimeout(() => void init(), 10000);
      }
    }

    void init();
    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [loadDaily]);

  useEffect(() => {
    if (!articles.length) return;
    let cancelled = false;
    const pollVoices = async () => {
      if (cancelled || isPlayingRef.current) return;
      await warmVoiceCache([0, 1, 2].filter((i) => i < articles.length));
    };
    void pollVoices();
    const timer = setInterval(() => void pollVoices(), 4000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [articles.length, voiceLang, warmVoiceCache]);

  useEffect(() => {
    if (!articles.length) return;
    void prewarmCaAudio(voiceLang).catch(() => {});
  }, [articles.length, voiceLang]);

  useEffect(() => {
    setVoiceLang(loadVoiceLanguage());
  }, []);

  useEffect(() => {
    if (!editionDate) return;
    setStudyProgress(loadDailyProgress(editionDate));
    setStreak(getStudyStreak());
  }, [editionDate]);

  useEffect(() => {
    return () => {
      playlistCancelRef.current = true;
      stopAudio();
    };
  }, []);

  const onPlaybackChange = useCallback(
    (state: AudioPlaybackState) => {
      if (wasPlayingRef.current && state === "idle" && activeArticleIndex !== null && editionDate) {
        const updated = markStoryListened(editionDate, activeArticleIndex);
        setStudyProgress(updated);
        setStreak(getStudyStreak());
      }
      wasPlayingRef.current = state === "playing";
      setPlaybackState(state);
      isPlayingRef.current = state === "playing";
    },
    [activeArticleIndex, editionDate]
  );

  function onReadArticle(index: number) {
    setReadIndex(index);
    document.getElementById("ca-read-stage")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function onListen(index: number) {
    playlistCancelRef.current = true;
    setPlaylistRunning(false);
    setPlaylistProgress("");
    setBusyIndex(index);
    setActiveArticleIndex(index);
    setReadIndex(index);
    setError("");
    stopAudio();

    const cached = briefingCacheRef.current.get(briefingCacheKey(index));
    if (cached?.audio_base64) {
      setBusyIndex(null);
      setActiveBriefing(cached);
      setAutoPlayBriefing(true);
      document.getElementById("ca-voice-stage")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }

    setAutoPlayBriefing(false);
    try {
      const briefing = await explainCurrentAffair(index, undefined, voiceLang);
      markVoiceReady(index, briefing);
      setActiveBriefing(briefing);
      setAutoPlayBriefing(Boolean(briefing.audio_base64));
      document.getElementById("ca-voice-stage")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voice briefing failed");
    } finally {
      setBusyIndex(null);
    }
  }

  async function onPlayFullEdition() {
    if (!articles.length || playlistRunning) return;
    playlistCancelRef.current = false;
    setPlaylistRunning(true);
    setError("");
    stopAudio();

    for (let i = 0; i < articles.length; i++) {
      if (playlistCancelRef.current) break;
      setBusyIndex(i);
      setActiveArticleIndex(i);
      setPlaylistProgress(`Story ${i + 1} of ${articles.length}`);
      setAutoPlayBriefing(false);
      try {
        const briefing = await explainCurrentAffair(i, undefined, voiceLang);
        markVoiceReady(i, briefing);
        setActiveBriefing(briefing);
        if (briefing.audio_base64) {
          isPlayingRef.current = true;
          await playBase64AudioAndWait(briefing.audio_base64);
          isPlayingRef.current = false;
          if (editionDate) {
            const updated = markStoryListened(editionDate, i);
            setStudyProgress(updated);
            setStreak(getStudyStreak());
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : `Briefing failed for story ${i + 1}`);
        break;
      }
    }

    isPlayingRef.current = false;
    setBusyIndex(null);
    setPlaylistRunning(false);
    setPlaylistProgress("");
  }

  function stopPlaylist() {
    playlistCancelRef.current = true;
    isPlayingRef.current = false;
    stopAudio();
    setPlaylistRunning(false);
    setPlaylistProgress("");
    setBusyIndex(null);
    setPlaybackState("idle");
  }

  function onContinueLearning() {
    if (activeArticleIndex === null || activeArticleIndex >= articles.length - 1) return;
    void onListen(activeArticleIndex + 1);
  }

  function onResumeWhereLeftOff() {
    if (!studyProgress || !articles.length) return;
    const firstUnheard = articles.findIndex((_, i) => !studyProgress.listened.includes(i));
    const index = firstUnheard >= 0 ? firstUnheard : 0;
    void onListen(index);
  }

  if (loading) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4">
        <div className="h-12 w-12 animate-spin rounded-full border-2 border-saffron/20 border-t-saffron" />
        <p className="max-w-md text-center text-sm text-slate-400">
          Loading today’s newspaper headlines…
        </p>
        <p className="text-xs text-slate-600">The Hindu · Indian Express · Mint · Business Standard</p>
      </div>
    );
  }

  const statusLabel = isLive
    ? "Live newspapers"
    : isPreparing
      ? "Preparing headlines"
      : isFallback
        ? "Curated edition"
        : "Syncing…";

  const listened = studyProgress?.listened ?? [];
  const completedCount = listened.length;
  const totalCount = articles.length;
  const minsLeft = Math.max(0, (totalCount - completedCount) * 1);
  const hasPartialProgress =
    studyProgress &&
    studyProgress.listened.length > 0 &&
    studyProgress.listened.length < totalCount;

  return (
    <div className="space-y-8 pb-10">
      {/* Hero — student-first */}
      <section className="relative overflow-hidden rounded-3xl border border-white/10 bg-mesh px-6 py-10 text-center md:px-10">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-saffron/5 to-transparent" />
        <div className="relative animate-fade-up">
          <p className="section-label">{greeting()}, aspirant</p>
          <h1 className="mt-2 font-display text-3xl font-bold tracking-tight md:text-5xl">
            Today’s{" "}
            <span className="bg-gradient-to-r from-saffron to-india-green bg-clip-text text-transparent">
              Current Affairs
            </span>
          </h1>
          <p className="mx-auto mt-3 max-w-lg text-slate-400">
            Skip the full newspaper. Aayan teaches the story in your language — what it is, what
            happened, and what to keep for the exam.
          </p>

          <div className="mx-auto mt-6 max-w-md text-left">
            <label htmlFor="ca-voice-lang" className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
              Class language
            </label>
            <select
              id="ca-voice-lang"
              value={voiceLang}
              onChange={(e) => {
                const next = e.target.value as CaVoiceLangCode;
                setVoiceLang(next);
                saveVoiceLanguage(next);
                briefingCacheRef.current.clear();
                setVoiceReadyIndexes(new Set());
                setActiveBriefing(null);
                stopAudio();
              }}
              className="mt-1.5 w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2.5 text-sm text-slate-100 outline-none ring-saffron/40 focus:ring-2"
            >
              {CA_VOICE_LANGUAGES.map((lang) => (
                <option key={lang.code} value={lang.code}>
                  {lang.name} · {lang.native_name}
                </option>
              ))}
            </select>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <span
              className={`ca-pill ${isLive ? "ca-pill--live" : ""} ${
                isLive ? "" : "border-amber-500/30 text-amber-200"
              }`}
            >
              {statusLabel}
            </span>
            <span className="ca-pill">{editionDate || "Today"}</span>
            {voicesReady > 0 ? (
              <span className="ca-pill ca-pill--live">{voicesReady} voices ready</span>
            ) : null}
            {playbackState === "playing" ? (
              <span className="ca-pill ca-pill--live animate-pulse">▶ Now playing</span>
            ) : null}
          </div>

          {/* Value props */}
          <div className="mx-auto mt-8 grid max-w-2xl grid-cols-3 gap-3">
            <div className="study-value-card">
              <p className="font-display text-2xl font-bold text-saffron">{totalCount}</p>
              <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-500">Stories</p>
            </div>
            <div className="study-value-card">
              <p className="font-display text-2xl font-bold text-india-green">~{totalCount}m</p>
              <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-500">Total time</p>
            </div>
            <div className="study-value-card">
              <p className="font-display text-2xl font-bold text-white">3-in-1</p>
              <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-500">Prelims·Mains·IV</p>
            </div>
          </div>

          {articles.length > 0 && (
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              {!playlistRunning ? (
                <>
                  <button
                    type="button"
                    disabled={busyIndex !== null}
                    onClick={() => void onPlayFullEdition()}
                    className="btn-primary inline-flex items-center gap-2 px-8 py-3.5 text-base"
                  >
                    <span className="text-lg">▶</span>
                    Play full edition
                  </button>
                  {hasPartialProgress ? (
                    <button
                      type="button"
                      disabled={busyIndex !== null}
                      onClick={onResumeWhereLeftOff}
                      className="btn-secondary px-6 py-3.5 text-base"
                    >
                      Resume
                    </button>
                  ) : null}
                </>
              ) : (
                <button type="button" onClick={stopPlaylist} className="btn-secondary px-8 py-3.5 text-base">
                  Stop
                </button>
              )}
              {playlistProgress ? (
                <span className="text-sm text-india-green">{playlistProgress}</span>
              ) : null}
            </div>
          )}
        </div>
      </section>

      {totalCount > 0 ? (
        <StudyProgressBar
          completed={completedCount}
          total={totalCount}
          streak={streak}
          estimatedMinsLeft={minsLeft}
        />
      ) : null}

      <StudyTipBanner />

      {readIndex !== null && articles[readIndex] ? (
        <div id="ca-read-stage" className="animate-fade-up space-y-4">
          <CaArticleDetail article={articles[readIndex]} index={readIndex} total={totalCount} />
        </div>
      ) : null}

      {activeBriefing && activeArticleIndex !== null ? (
        <div id="ca-voice-stage" className="animate-fade-up">
          <CaBriefingCard
            briefing={activeBriefing}
            autoPlay={autoPlayBriefing}
            onPlaybackChange={onPlaybackChange}
            editionLabel={`Story ${activeArticleIndex + 1} / ${totalCount}`}
            hasNext={activeArticleIndex < totalCount - 1}
            onNextStory={onContinueLearning}
            isDone={listened.includes(activeArticleIndex)}
          />
        </div>
      ) : null}

      {error ? (
        <p className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-center text-sm text-red-300">
          {error}
        </p>
      ) : null}

      {/* Story list */}
      <section>
        <div className="mb-5 flex items-end justify-between gap-4">
          <div>
            <p className="section-label">Today&apos;s headlines</p>
            <h2 className="mt-1 font-display text-xl font-semibold text-slate-100">
              Where should you start?
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Read the notes, then listen — the voice is the classroom
            </p>
          </div>
          {refreshing ? (
            <span className="text-xs text-slate-500">Updating…</span>
          ) : null}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          {articles.map((article, index) => {
            const isActive = activeArticleIndex === index;
            const isReading = readIndex === index;
            const isBusy = busyIndex === index;
            const isDone = listened.includes(index);
            const voiceReady = voiceReadyIndexes.has(index);
            const extraTags = Math.max(0, article.gs_tags.length - 3);
            return (
              <article
                key={`${article.title}-${index}`}
                role="button"
                tabIndex={0}
                onClick={() => onReadArticle(index)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onReadArticle(index);
                  }
                }}
                className={`glass-card group relative cursor-pointer transition-all duration-300 ${
                  isDone ? "article-card--done" : ""
                } ${isActive || isReading ? "article-card--active" : "hover:border-white/15"}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex flex-wrap gap-1.5">
                    {article.is_prelims_relevant ? (
                      <span className="exam-badge exam-badge--prelims">Prelims</span>
                    ) : null}
                    <span className="exam-badge exam-badge--mains">Mains</span>
                    {isDone ? (
                      <span className="exam-badge border-india-green/30 bg-india-green/10 text-india-green">
                        ✓ Done
                      </span>
                    ) : null}
                  </div>
                  <span className="font-display text-2xl font-bold text-white/10">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                </div>

                <p className="mt-3 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                  {article.source}
                </p>
                <h3 className="mt-1.5 font-display text-lg font-semibold leading-snug text-slate-100">
                  {article.title}
                </h3>

                <div className="mt-3 rounded-lg border border-white/[0.04] bg-black/20 px-3 py-2">
                  <p className="text-[9px] font-bold uppercase tracking-widest text-slate-600">
                    Revision points
                  </p>
                  <ul className="mt-1.5 space-y-1">
                    {article.key_highlights.slice(0, 2).map((h) => (
                      <li key={h} className="line-clamp-2 text-xs leading-relaxed text-slate-400">
                        · {h}
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {article.gs_tags.slice(0, 3).map((tag) => (
                    <GsTag key={tag} tag={tag} />
                  ))}
                  {extraTags > 0 ? (
                    <span className="ca-pill text-[9px]">+{extraTags} more</span>
                  ) : null}
                </div>

                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onReadArticle(index);
                    }}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-white/5 py-2.5 text-xs font-semibold text-slate-300 transition hover:border-saffron/30 hover:text-saffron"
                  >
                    📖 Read
                  </button>
                  <button
                    type="button"
                    disabled={busyIndex !== null && !isBusy}
                    onClick={(e) => {
                      e.stopPropagation();
                      void onListen(index);
                    }}
                    className={`flex flex-[1.4] items-center justify-center gap-2 rounded-xl py-2.5 text-xs font-semibold transition ${
                    isActive
                      ? "border border-india-green/40 bg-india-green/10 text-india-green"
                      : isDone
                        ? "border border-white/10 bg-white/5 text-slate-300 hover:border-saffron/30 hover:text-saffron"
                        : "bg-gradient-to-r from-saffron/90 to-saffron-light text-navy-deep hover:brightness-110"
                  }`}
                >
                  {isBusy ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                      Preparing voice…
                    </>
                  ) : isActive && playbackState === "playing" ? (
                    <>🎧 Listening…</>
                  ) : voiceReady ? (
                    <>
                      <span>⚡</span> Listen now
                    </>
                  ) : isDone ? (
                    <>🔁 Listen again</>
                  ) : (
                    <>
                      <span>🎧</span> Listen
                    </>
                  )}
                </button>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}
