import type { CASource, RetrievedChunk } from "@/lib/types";

export function RetrievalSidebar({
  chunks,
  caSource,
  dafFocus,
  phase,
}: {
  chunks: RetrievedChunk[];
  caSource?: CASource | null;
  dafFocus?: string;
  phase?: string;
}) {
  const isCA = phase === "current_affairs";
  const isSubject = phase === "subject_probe";

  return (
    <aside className="glass-card h-fit lg:sticky lg:top-24">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <p className="section-label">Context</p>
          <h3 className="mt-1 font-semibold text-slate-100">
            {isCA ? "Current Affairs" : isSubject ? "Subject RAG" : "DAF Focus"}
          </h3>
        </div>
        <span className="rounded-full bg-saffron/15 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-saffron">
          {phase?.replace(/_/g, " ") || "interview"}
        </span>
      </div>

      {dafFocus && (
        <div className="mb-4 rounded-xl border border-saffron/25 bg-gradient-to-br from-saffron/10 to-transparent p-4">
          <div className="flex items-center gap-2">
            <span className="text-sm">📌</span>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-saffron/70">DAF Anchor</p>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-slate-200">{dafFocus}</p>
        </div>
      )}

      {caSource && (
        <div
          className={`mb-4 rounded-xl border p-4 ${
            caSource.grounded
              ? "border-emerald-500/30 bg-emerald-500/8"
              : "border-amber-500/30 bg-amber-500/8"
          }`}
        >
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-semibold uppercase tracking-widest opacity-60">Featured News</p>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
              caSource.grounded ? "bg-emerald-500/20 text-emerald-300" : "bg-amber-500/20 text-amber-300"
            }`}>
              {(caSource.grounding_score * 100).toFixed(0)}%
            </span>
          </div>
          <p className="mt-2 text-sm font-medium leading-snug text-slate-100">{caSource.title}</p>
        </div>
      )}

      {chunks.length === 0 ? (
        <div className="rounded-xl border border-dashed border-white/10 p-6 text-center">
          <p className="text-2xl opacity-30">{isCA ? "📰" : isSubject ? "📚" : "📋"}</p>
          <p className="mt-2 text-xs text-slate-500">
            {isCA || isSubject ? "No RAG chunks retrieved yet." : "DAF-only phase — questions from your form."}
          </p>
        </div>
      ) : (
        <ul className="max-h-[45vh] space-y-2 overflow-y-auto">
          {chunks.map((chunk, i) => (
            <li
              key={i}
              className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3 transition hover:border-saffron/20"
            >
              <span className="inline-block rounded-md bg-saffron/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-saffron">
                {chunk.doc_type.replace(/_/g, " ")}
              </span>
              <p className="mt-2 text-xs leading-relaxed text-slate-400">
                {chunk.preview || chunk.text}
              </p>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
