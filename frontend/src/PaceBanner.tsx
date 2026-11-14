import { useEffect, useState } from "react";
import { api } from "./api";

// Asks the server whether this student is moving unusually fast. Timing data stays server-side.
export default function PaceBanner({ lessonId, signal, enabled }: { lessonId: number | null; signal: unknown; enabled: boolean }) {
  const [assessment, setAssessment] = useState<{ lessonId: number; tooFast: boolean } | null>(null);
  const [dismissed, setDismissed] = useState<Set<number>>(() => new Set());
  useEffect(() => {
    if (!enabled || !lessonId) { setAssessment(null); return; }
    let live = true;
    api(`assignments/${lessonId}/pace/`, {}).then((d) => { if (live) setAssessment({ lessonId, tooFast: d.too_fast === true }); }).catch(() => {});
    return () => { live = false; };
  }, [lessonId, signal, enabled]);
  if (!enabled || !lessonId || assessment?.lessonId !== lessonId || !assessment.tooFast || dismissed.has(lessonId)) return null;
  return (
    <div className="pace-banner" role="alert">
      <span><strong>Slow down.</strong> Don't rely on AI to complete these exercises — you won't be learning if it does the thinking for you. Take your time and work through them yourself.</span>
      <button aria-label="Dismiss" onClick={() => setDismissed((previous) => new Set(previous).add(lessonId))}>×</button>
    </div>
  );
}
