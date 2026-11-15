import { useEffect, useState } from "react";
import { ArrowUpRight, MessageCircle, Search } from "lucide-react";
import { api } from "./api";
import { readRoute, routeHref } from "./navigation";

type Suggestion = {
  id: number;
  title: string;
  excerpt: string;
  answer_label: string;
};

export default function RelatedDiscussions({ title, body, excludeId }: {
  title: string; body: string; excludeId: number | null;
}) {
  const courseId = readRoute().courseId;
  const text = `${title.trim()}\n${body.trim()}`.trim().slice(0, 1500);
  const [result, setResult] = useState<{
    key: string; rows: Suggestion[]; error: boolean;
  } | null>(null);
  const [retry, setRetry] = useState(0);
  const key = JSON.stringify([courseId, excludeId, text]);
  useEffect(() => {
    if (text.length < 12) return;
    let current = true;
    const timer = window.setTimeout(() => {
      api("discussions/suggestions/", { text, exclude_id: excludeId }, courseId)
        .then(data => { if (current) setResult({ key, rows: data.suggestions, error: false }); })
        .catch(() => { if (current) setResult({ key, rows: [], error: true }); });
    }, 500);
    return () => { current = false; window.clearTimeout(timer); };
  }, [key, text, excludeId, courseId, retry]);
  if (text.length < 12) return null;
  const matching = result?.key === key ? result : null;
  return <section className="db-related" aria-label="Related answered questions" aria-busy={!matching}>
    <header><Search size={17} /><strong>Already answered?</strong></header>
    <p>Check a related question without leaving your draft.</p>
    <div aria-live="polite">
      {!matching ? <small>Looking for related answers…</small> : matching.error ?
        <div className="db-related-retry">Related answers couldn’t load. You can still post your question. <button type="button" onClick={() => { setResult(null); setRetry(value => value + 1); }}>Try again</button></div> :
        matching.rows.length ? <ul>{matching.rows.map(row => <li key={row.id}>
          <a href={routeHref({ page: "discussions", courseId, post: row.id })} target="_blank" rel="noopener noreferrer" aria-label={`${row.title} (opens in a new tab)`}>
            <MessageCircle size={17} aria-hidden="true" /><span><strong>{row.title}</strong><small>{row.excerpt}</small><em>{row.answer_label}</em></span><ArrowUpRight size={16} aria-hidden="true" />
          </a>
        </li>)}</ul> : <small>No close answered questions yet. Keep writing your question.</small>}
    </div>
  </section>;
}
