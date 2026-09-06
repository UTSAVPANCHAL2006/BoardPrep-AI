"use client";

import { useEffect, useState } from "react";

const TIPS = [
  "After each story, lock one Prelims fact — that is what the paper actually asks.",
  "Write the Mains angle in two lines in your notes before you move on.",
  "Say the interview line out loud once — it builds recall under pressure.",
  "While you listen, picture the newspaper headline. Retention jumps.",
  "Match the GS tags to your syllabus map so the story sits in the right paper.",
  "Play the full edition on a walk or commute — treat it as one class, not ten tabs.",
];

export function StudyTipBanner() {
  const [tip, setTip] = useState(TIPS[0]);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const dayIndex = new Date().getDate() % TIPS.length;
    setTip(TIPS[dayIndex]);
  }, []);

  if (!visible) return null;

  return (
    <div className="study-tip-banner">
      <span className="text-base" aria-hidden>
        💡
      </span>
      <p className="flex-1 text-sm leading-relaxed text-slate-300">
        <span className="font-semibold text-saffron">Pro tip: </span>
        {tip}
      </p>
      <button
        type="button"
        onClick={() => setVisible(false)}
        className="shrink-0 text-slate-500 transition hover:text-slate-300"
        aria-label="Dismiss tip"
      >
        ✕
      </button>
    </div>
  );
}
