"use client";

import type { EnrichedArticle } from "@/lib/types";

function gsTagTone(tag: string): "gs1" | "gs2" | "gs3" | "gs4" | "prelims" | "default" {
  const t = tag.toLowerCase();
  if (t === "prelims" || t.startsWith("prelims")) return "prelims";
  if (t.includes("gs1") || t.includes("gs 1")) return "gs1";
  if (t.includes("gs2") || t.includes("gs 2")) return "gs2";
  if (t.includes("gs3") || t.includes("gs 3")) return "gs3";
  if (t.includes("gs4") || t.includes("gs 4")) return "gs4";
  return "default";
}

const TONE_CLASS: Record<ReturnType<typeof gsTagTone>, string> = {
  gs1: "gs-tag gs-tag--gs1",
  gs2: "gs-tag gs-tag--gs2",
  gs3: "gs-tag gs-tag--gs3",
  gs4: "gs-tag gs-tag--gs4",
  prelims: "gs-tag gs-tag--prelims",
  default: "gs-tag",
};

export function GsTag({ tag }: { tag: string }) {
  return <span className={TONE_CLASS[gsTagTone(tag)]}>{tag}</span>;
}

export function CaArticleDetail({
  article,
  index,
  total,
}: {
  article: EnrichedArticle;
  index: number;
  total: number;
}) {
  const concepts = Object.entries(article.key_concepts || {});
  const summary =
    article.key_highlights[0] ||
    (article.detailed_insights ? article.detailed_insights.slice(0, 180) : "");

  return (
    <article className="ca-article-detail">
      <div className="flex flex-wrap items-center gap-2">
        <span className="ca-pill">{article.source}</span>
        <span className="ca-pill">Story {index + 1} / {total}</span>
        {article.is_prelims_relevant ? (
          <span className="exam-badge exam-badge--prelims">Prelims</span>
        ) : null}
      </div>

      <h2 className="mt-4 font-display text-2xl font-bold leading-snug text-white md:text-3xl">
        {article.title}
      </h2>

      {summary ? (
        <p className="mt-3 text-sm leading-relaxed text-slate-400">{summary}</p>
      ) : null}

      {article.gs_tags.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {article.gs_tags.map((tag) => (
            <GsTag key={tag} tag={tag} />
          ))}
        </div>
      ) : null}

      {article.url ? (
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex items-center gap-1 text-sm text-saffron hover:underline"
        >
          Read original article →
        </a>
      ) : null}

      {article.key_highlights.length > 0 ? (
        <section className="ca-detail-section">
          <h3 className="ca-detail-heading">Key Highlights</h3>
          <ul className="mt-3 space-y-2.5">
            {article.key_highlights.map((h) => (
              <li key={h} className="flex gap-2.5 text-sm leading-relaxed text-slate-300">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-saffron" />
                {h}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {article.detailed_insights ? (
        <section className="ca-detail-section">
          <h3 className="ca-detail-heading">Detailed Insights</h3>
          <p className="mt-3 text-sm leading-relaxed text-slate-300">{article.detailed_insights}</p>
        </section>
      ) : null}

      {concepts.length > 0 ? (
        <section className="ca-detail-section">
          <h3 className="ca-detail-heading">Key Concepts Involved</h3>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {concepts.map(([term, def]) => (
              <div key={term} className="ca-concept-card">
                <p className="font-semibold text-slate-100">{term}</p>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{def}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </article>
  );
}
