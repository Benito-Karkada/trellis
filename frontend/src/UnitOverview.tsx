import { useRef, useState } from "react";
import type { CSSProperties, MouseEvent } from "react";
import { ArrowUpRight, ChevronDown, Check, ClipboardList, PackageOpen, X } from "lucide-react";
import { readRoute, routeHref } from "./navigation";
import { unitColor } from "./unitColors";

type Part = { id: number; title: string; status: string; earned_points: string; maximum_points: string; metadata?: { kind?: string; category?: string } };
type Lesson = { id: number; title: string; metadata?: { kind?: string; unit_number?: number; earned_points?: string; maximum_points?: string; activity_count?: number; completed_count?: number }; activities: Part[] };

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
const preferenceKey = "trellis:unboxed-units:v1"; // kept so students' saved open/closed units carry over
function initialOpened(key:string) { try { const saved: unknown = JSON.parse(localStorage.getItem(key) || "[]"); return new Set(Array.isArray(saved) ? saved.filter((id): id is string => typeof id === "string") : []); } catch { return new Set<string>(); } }

export default function UnitOverview({ lessons, quizzes, onOpen, example=true }: { example?:boolean; lessons: Lesson[]; quizzes: Lesson[]; onOpen: (lesson: number, part: number | null) => void }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const keyForCourse = preferenceKey+":"+readRoute().courseId;
  const [opened, setOpened] = useState(()=>initialOpened(keyForCourse));
  const groupOf=(lesson:Lesson)=>example?unitOf(lesson):`section:${lesson.id}`;
  const groupQuiz=(quiz:Lesson)=>example?quizUnit(quiz):`section:${quiz.id}`;
  const openButtons = useRef<Record<string, HTMLButtonElement | null>>({});
  const closeButtons = useRef<Record<string, HTMLButtonElement | null>>({});
  const keys = [...new Set([...lessons.map(groupOf), ...quizzes.map(groupQuiz)])];
  function toggle(key: string) {
    const opening = !opened.has(key), next = new Set(opened);
    if (opening) next.add(key); else next.delete(key);
    setOpened(next);
    try { localStorage.setItem(keyForCourse, JSON.stringify([...next])); } catch { /* Still works without storage. */ }
    requestAnimationFrame(() => { (opening ? closeButtons : openButtons).current[key]?.focus({ preventScroll: true }); });
  }
  function link(lesson: Lesson, part?: Part) { const target = part || lesson.activities[0]; return routeHref({ page: "course", lessonId: lesson.id, active: target?.id || null, category: target?.metadata?.category || "content" }); }
  function click(event: MouseEvent, lesson: Lesson, part?: Part) { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); onOpen(lesson.id, part?.id || lesson.activities[0]?.id || null); }
  return (
    <section className="ch-units" aria-label="Course units">
      <div className="ch-units-heading">
        <span className="ch-kicker ch-kicker-accent">YOUR COURSE</span>
        <h2>Course units</h2>
      </div>
      <div className="ch-units-scroll">
        <div className="ch-unit-grid">
          {keys.map((key) => {
            const chapters = lessons.filter((l) => groupOf(l) === key), assessments = quizzes.filter((q) => groupQuiz(q) === key), isOpen = opened.has(key);
            const count = chapters.reduce((n, l) => n + (l.metadata?.activity_count ?? l.activities.length), 0), done = chapters.reduce((n, l) => n + (l.metadata?.completed_count ?? l.activities.filter((a) => a.status === "completed").length), 0);
            const label = !example ? "SECTION" : key === "final" ? "FINALE" : key === "other" ? "EXTRA" : `UNIT ${key}`;
            const openLabel = !example ? "Open section" : key === "final" ? "Open Set" : key === "other" ? "Open Coursework" : `Open Unit ${key}`;
            return (
              <article key={key} className={`ch-unit-card ${isOpen ? "is-open" : ""}`} style={{ "--unit-color": unitColor(key) } as CSSProperties}>
                <header className="ch-unit-head">
                  <span className="ch-unit-badge">{!example ? String(keys.indexOf(key)+1).padStart(2,"0") : key === "final" ? <Check size={22} strokeWidth={3} aria-hidden="true" /> : key === "other" ? "+" : key.padStart(2, "0")}</span>
                  <div className="ch-unit-titles">
                    <span className="ch-kicker">{label}</span>
                    <h3>{!example ? (chapters[0]?.title || assessments[0]?.title) : names[key] || `Unit ${key}`}</h3>
                  </div>
                  <span className="ch-unit-fraction"><b>{done}</b> / {count}</span>
                  {isOpen && <button ref={(node) => { closeButtons.current[key] = node; }} className="ch-unit-close" aria-label={`Close ${label.toLowerCase()}`} onClick={() => toggle(key)}><X size={16} /></button>}
                </header>
                <progress className="ch-unit-progress" aria-label={`${!example ? (chapters[0]?.title || assessments[0]?.title) : names[key] || key} progress`} value={done} max={count || 1} />
                {!isOpen ? (
                  <>
                    <p className="ch-unit-meta">{example ? `${chapters.length} chapter${chapters.length===1?"":"s"}` : `${count} part${count===1?"":"s"}`}</p>
                    <button ref={(node) => { openButtons.current[key] = node; }} className="ch-unit-open" aria-expanded={false} aria-controls={`unit-contents-${key}`} onClick={() => toggle(key)}>{openLabel}</button>
                  </>
                ) : (
                  <div id={`unit-contents-${key}`} className="ch-unit-contents" role="region" aria-label={`${label} chapters and quizzes`} tabIndex={0}>
                    <div className="ch-chapters">
                      {chapters.map((chapter) => {
                        const open = expanded.has(chapter.id), total = chapter.metadata?.activity_count ?? chapter.activities.length, completed = chapter.metadata?.completed_count ?? chapter.activities.filter((a) => a.status === "completed").length;
                        const earned = Number(chapter.metadata?.earned_points || 0), maximum = Number(chapter.metadata?.maximum_points || 0);
                        const pset = chapter.activities.find((a) => a.metadata?.category === "problem_set");
                        return (
                          <section key={chapter.id} className="ch-chapter">
                            <div className="ch-chapter-head">
                              <button className="ch-chapter-toggle" aria-label={`${open ? "Collapse" : "Expand"} ${chapter.title}`} aria-expanded={open} aria-controls={`chapter-parts-${chapter.id}`}
                                onClick={() => setExpanded((old) => { const next = new Set(old); if (next.has(chapter.id)) next.delete(chapter.id); else next.add(chapter.id); return next; })}>
                                <ChevronDown size={17} />
                              </button>
                              <a className="ch-chapter-link" href={link(chapter)} onClick={(e) => click(e, chapter)}>
                                <strong>{chapter.title.replace(/^Chapter\s*/i, "").replace(/(\d+\.\d+)\s*[-–—]\s*/, "$1 · ")}</strong>
                                <small>{total} parts{maximum > 0 ? ` · ${points(earned)} / ${points(maximum)} points` : ""}</small>
                              </a>
                              {completed === total && total > 0
                                ? <Check className="ch-chapter-done" size={18} aria-label="Complete" />
                                : <a className="ch-chapter-go" aria-label={`Open ${chapter.title}`} href={link(chapter)} onClick={(e) => click(e, chapter)}><ArrowUpRight size={18} /></a>}
                            </div>
                            {open && (
                              <div id={`chapter-parts-${chapter.id}`} className="ch-parts">
                                {chapter.activities.filter((a) => a.metadata?.category !== "problem_set").map((part) => (
                                  <a key={part.id} href={link(chapter, part)} onClick={(e) => click(e, chapter, part)}>
                                    <span className={`ch-part-dot ${part.status === "completed" ? "done" : ""}`}>{part.status === "completed" && <Check size={10} />}</span>{part.title}
                                  </a>
                                ))}
                                {pset && <a className="ch-pset-link" href={link(chapter, pset)} onClick={(e) => click(e, chapter, pset)}><PackageOpen size={15} />Problem set<ArrowUpRight size={15} /></a>}
                              </div>
                            )}
                          </section>
                        );
                      })}
                    </div>
                    {!!assessments.length && (
                      <div className="ch-quizzes">
                        <span className="ch-kicker">PROGRAMMING QUIZZES</span>
                        {assessments.map((quiz) => (
                          <a key={quiz.id} href={link(quiz)} onClick={(e) => click(e, quiz)}>
                            <ClipboardList size={18} aria-hidden="true" />
                            <span><strong>{quiz.title}</strong><small>{quiz.metadata?.activity_count ?? quiz.activities.length} questions · {points(Number(quiz.metadata?.earned_points || 0))} / {points(Number(quiz.metadata?.maximum_points || 0))} points</small></span>
                            <ArrowUpRight size={18} />
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
