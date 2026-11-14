import type { CSSProperties, MouseEvent } from "react";
import { ArrowUpRight, Check, ClipboardList, MessageCircle } from "lucide-react";
import { routeHref } from "./navigation";
import { unitColor } from "./unitColors";

type Part = { id: number; title: string; status: string; earned_points: string; maximum_points: string; metadata?: { kind?: string; category?: string } };
type Lesson = { id: number; title: string; metadata?: { kind?: string; unit_number?: number; earned_points?: string; maximum_points?: string; activity_count?: number; completed_count?: number }; activities: Part[] };

/** Every unit card shows this many rows; any extra rows scroll inside the card. */
const VISIBLE_ROWS = 5;

const names: Record<string, string> = {
  "1": "Computing Foundations",
  "2": "Procedural Programming",
  "3": "Control Structures",
  "4": "Data Structures",
  "5": "Objects & Algorithms",
  final: "Final Problem Set",
  other: "More Coursework",
};
function unitOf(lesson: Lesson) { return lesson.title.match(/(?:Chapter|Unit)\s+(\d+)/i)?.[1] || (/final/i.test(lesson.title) ? "final" : "other"); }
function quizUnit(quiz: Lesson) { const number = Number(quiz.title.match(/(\d+)\s*$/)?.[1]); return String(quiz.metadata?.unit_number || ({ 1: 3, 2: 3, 3: 3, 4: 4, 5: 4, 6: 5 } as Record<number, number>)[number] || "other"); }
const points = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function UnitOverview({ lessons, quizzes, onOpen, onDiscussions, example = true }: { example?: boolean; lessons: Lesson[]; quizzes: Lesson[]; onOpen: (lesson: number, part: number | null) => void; onDiscussions?: () => void }) {
  const groupOf = (lesson: Lesson) => example ? unitOf(lesson) : `section:${lesson.id}`;
  const groupQuiz = (quiz: Lesson) => example ? quizUnit(quiz) : `section:${quiz.id}`;
  const keys = [...new Set([...lessons.map(groupOf), ...quizzes.map(groupQuiz)])];
  function link(lesson: Lesson) { const target = lesson.activities[0]; return routeHref({ page: "course", lessonId: lesson.id, active: target?.id || null, category: target?.metadata?.category || "content" }); }
  function click(event: MouseEvent, lesson: Lesson) { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); onOpen(lesson.id, lesson.activities[0]?.id || null); }
  return (
    <section className="ch-units" aria-label="Course units">
      <div className="ch-units-heading">
        <div><span className="ch-kicker ch-kicker-accent">YOUR COURSE</span><h2>Course units</h2></div>
        {onDiscussions && <button className="ch-discussion-shortcut" aria-label="Open discussion board" title="Discussion board" onClick={onDiscussions}><MessageCircle size={23} strokeWidth={1.8} /></button>}
      </div>
      <div className="ch-units-scroll">
        <div className="ch-unit-grid">
          {keys.map((key) => {
            const chapters = lessons.filter((l) => groupOf(l) === key), assessments = quizzes.filter((q) => groupQuiz(q) === key);
            const count = chapters.reduce((n, l) => n + (l.metadata?.activity_count ?? l.activities.length), 0), done = chapters.reduce((n, l) => n + (l.metadata?.completed_count ?? l.activities.filter((a) => a.status === "completed").length), 0);
            const label = !example ? "SECTION" : key === "final" ? "FINALE" : key === "other" ? "EXTRA" : `UNIT ${key}`;
            const title = example ? (names[key] || `Unit ${key}`) : (chapters[0]?.title || assessments[0]?.title);
            const rowCount = chapters.length + assessments.length, scrolls = rowCount > VISIBLE_ROWS;
            return (
              <article key={key} className="ch-unit-card" style={{ "--unit-color": unitColor(key), "--unit-visible-rows": VISIBLE_ROWS } as CSSProperties}>
                <header className="ch-unit-head">
                  <span className="ch-unit-badge">{!example ? String(keys.indexOf(key) + 1).padStart(2, "0") : key === "final" ? <Check size={22} strokeWidth={3} aria-hidden="true" /> : key === "other" ? "+" : key.padStart(2, "0")}</span>
                  <div className="ch-unit-titles">
                    <span className="ch-kicker">{label}</span>
                    <h3>{title}</h3>
                  </div>
                  <span className="ch-unit-fraction"><b>{done}</b> / {count}</span>
                </header>
                <progress className="ch-unit-progress" aria-label={`${title} progress`} value={done} max={count || 1} />
                {/* Always the height of VISIBLE_ROWS rows, so every unit card is the same size. */}
                <div className="ch-unit-list" role="region" aria-label={`${label} chapters and quizzes`} tabIndex={scrolls ? 0 : undefined}>
                  {chapters.map((chapter) => {
                    const total = chapter.metadata?.activity_count ?? chapter.activities.length, completed = chapter.metadata?.completed_count ?? chapter.activities.filter((a) => a.status === "completed").length;
                    const earned = Number(chapter.metadata?.earned_points || 0), maximum = Number(chapter.metadata?.maximum_points || 0);
                    return (
                      <a key={chapter.id} className="ch-unit-row" title={chapter.title} href={link(chapter)} onClick={(e) => click(e, chapter)}>
                        <span className="ch-unit-row-text">
                          <strong>{chapter.title.replace(/^Chapter\s*/i, "").replace(/(\d+\.\d+)\s*[-–—]\s*/, "$1 · ")}</strong>
                          <small>{total} parts{maximum > 0 ? ` · ${points(earned)} / ${points(maximum)} points` : ""}</small>
                        </span>
                        {completed === total && total > 0 ? <Check className="ch-row-done" size={18} aria-label="Complete" /> : <ArrowUpRight size={18} aria-hidden="true" />}
                      </a>
                    );
                  })}
                  {assessments.map((quiz) => (
                    <a key={quiz.id} className="ch-unit-row ch-unit-row-quiz" title={quiz.title} href={link(quiz)} onClick={(e) => click(e, quiz)}>
                      <ClipboardList size={17} aria-hidden="true" />
                      <span className="ch-unit-row-text">
                        <strong>{quiz.title}</strong>
                        <small>{quiz.metadata?.activity_count ?? quiz.activities.length} questions · {points(Number(quiz.metadata?.earned_points || 0))} / {points(Number(quiz.metadata?.maximum_points || 0))} points</small>
                      </span>
                      <ArrowUpRight size={18} aria-hidden="true" />
                    </a>
                  ))}
                </div>
                <p className="ch-unit-meta">{example ? `${chapters.length} chapter${chapters.length === 1 ? "" : "s"}` : `${count} part${count === 1 ? "" : "s"}`}{scrolls ? " · scroll for more" : ""}</p>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
