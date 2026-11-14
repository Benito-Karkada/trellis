import { lazy, Suspense, useEffect, useState } from "react";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Play,
  Search,
  Users,
  RefreshCw,
} from "lucide-react";
import { api } from "./api";
const EditorPane = lazy(() => import("./EditorPane"));
type Lesson = {
  id: number;
  title: string;
  kind: string;
  maximum: string;
  parts: number;
};
type Student = {
  id: number;
  name: string;
  email: string;
  assignments: Record<
    string,
    {
      earned: string;
      maximum: string;
      completed_parts: number;
      submitted: boolean;
    }
  >;
};
type Attempt = {id:string;number:number;submitted_at:string;status:string;score?:string;maximum?:string;practice?:boolean};
type Work = {
  history?: Attempt[];
  selected_attempt?: string;
  attempt_result?: Record<string, unknown>;
  attempt_status?: string;
  entrypoint?: string;
  id: number;
  title: string;
  kind: string;
  revision: number;
  earned: string;
  maximum: string;
  completed: boolean;
  lesson_id: number;
  lesson_title: string;
  saved_at: string | null;
  files: Record<string, string>;
  latest_response: Record<string, unknown> | null;
  submitted_at: string | null;
};
type Review = {
  student: { id: number; name: string; email: string };
  lesson: { id: number | null; title: string; kind: string };
  attempt: { started_at: string | null; submitted_at: string | null };
  activities: Work[];
};
export default function Gradebook({
  theme,
  onBack,
}: {
  theme: "light" | "dark";
  onBack: () => void;
}) {
  const [lessons, setLessons] = useState<Lesson[]>([]),
    [students, setStudents] = useState<Student[]>([]),
    [query, setQuery] = useState(""),
    [view, setView] = useState<"students" | "assignments">("students"),
    [assignment, setAssignment] = useState(""),
    [page, setPage] = useState(0),
    [selection, setSelection] = useState<{
      student: number;
      lesson: number | null;
    } | null>(null),
    [detail, setDetail] = useState<Review | null>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [canvas, setCanvas] = useState<{
      configured: boolean;
      counts: Record<string, number>;
    }>({ configured: false, counts: {} });
  useEffect(() => {
    api("gradebook/")
      .then((d) => {
        setLessons(d.lessons);
        setStudents(d.students);
        setCanvas(d.canvas);
        setAssignment(
          String(
            d.lessons.find((l: Lesson) => Number(l.maximum) > 0)?.id ||
              d.lessons[0]?.id ||
              "",
          ),
        );
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    setPage(0);
  }, [query, view, assignment]);
  useEffect(() => {
    setDetail(null);
    if (!selection) return;
    let cancelled = false;
    api(
      `gradebook/detail/?summary=1&membership=${selection.student}${selection.lesson ? "&lesson=" + selection.lesson : ""}`,
    )
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [selection]);
  async function sync() {
    if (!canvas.configured) {
      setNotice(
        "Canvas sync is a placeholder until the course connection is configured. No grades have been sent.",
      );
      return;
    }
    if (
      !window.confirm(
        "Sync recorded grades for every active student to Canvas? This includes recorded zeros, may replace Canvas grades, and adds a dated progress comment for each student.",
      )
    )
      return;
    setBusy(true);
    try {
      const d = await api("gradebook/sync-canvas/", {});
      setNotice(
        `${d.queued} grade updates with progress comments queued. Delivery failures are retried.`,
      );
      setCanvas(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const selectedDetail = detail && selection && detail.student.id === selection.student &&
    (detail.lesson.id ?? null) === selection.lesson ? detail : null;
  const matches = students.filter((s) =>
      `${s.name} ${s.email}`.toLowerCase().includes(query.trim().toLowerCase()),
    ),
    visible = matches.slice(page * 50, (page + 1) * 50),
    graded = lessons.filter((l) => Number(l.maximum) > 0),
    columns =
      view === "assignments"
        ? lessons.filter((l) => String(l.id) === assignment)
        : graded;
  return (
    <div className="gradebook-shell">
      <header className="settings-header">
        <button className="settings-back" onClick={onBack}>
          <ArrowLeft size={18} />
          Back to home
        </button>
        <strong>Course gradebook</strong>
        <div />
      </header>
      <main className="gradebook-main">
        <div className="gradebook-heading">
          <div>
            <span className="auth-kicker">CS 1301</span>
            <h1>Gradebook</h1>
            <p>
              Click a student’s name to review their work across the entire
              course.
            </p>
          </div>
          <button className="primary" onClick={sync} disabled={busy}>
            <RefreshCw size={16} />
            Sync grades to Canvas{!canvas.configured && " · Not connected"}
          </button>
        </div>
        <div className="gradebook-tools">
          <div className="view-toggle">
            <button
              className={view === "students" ? "active" : ""}
              onClick={() => setView("students")}
            >
              <Users size={16} />
              By student
            </button>
            <button
              className={view === "assignments" ? "active" : ""}
              onClick={() => setView("assignments")}
            >
              By assignment
            </button>
          </div>
          {view === "assignments" && (
            <label>
              Assignment
              <select
                value={assignment}
                onChange={(e) => setAssignment(e.target.value)}
              >
                {lessons.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.title}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            <Search size={16} />
            <input
              aria-label="Search students"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search student name or email"
            />
          </label>
        </div>
        {error && <div className="notification error">{error}</div>}
        {notice && <div className="notification">{notice}</div>}
        <div className="grade-table-wrap">
          <table className="grade-table">
            <thead>
              <tr>
                <th>Student</th>
                {columns.map((l) => (
                  <th key={l.id}>
                    {l.title}
                    <small>
                      {Number(l.maximum) > 0
                        ? l.maximum + " points"
                        : "Ungraded"}
                    </small>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((s) => (
                <tr key={s.id}>
                  <th>
                    <button
                      className="student-course-link"
                      onClick={() =>
                        setSelection({ student: s.id, lesson: null })
                      }
                    >
                      <strong>{s.name || s.email}</strong>
                      {s.name && <small>{s.email}</small>}
                      <span>Review entire course</span>
                    </button>
                  </th>
                  {columns.map((l) => {
                    const v = s.assignments[String(l.id)];
                    return (
                      <td key={l.id}>
                        <button
                          onClick={() =>
                            setSelection({ student: s.id, lesson: l.id })
                          }
                        >
                          <Score
                            earned={v?.earned || "0"}
                            maximum={l.maximum}
                            submitted={v?.submitted}
                          />
                          <ChevronRight size={14} />
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {!matches.length && (
            <div className="empty-state">No students match this search.</div>
          )}
        </div>
        <div className="gradebook-pagination">
          <span>
            {matches.length
              ? `${page * 50 + 1}–${Math.min((page + 1) * 50, matches.length)}`
              : "0"}{" "}
            of {matches.length} students
          </span>
          <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <button
            disabled={(page + 1) * 50 >= matches.length}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
        {selection && !selectedDetail && <p role="status">Loading student work…</p>}
        {selectedDetail && selection && (
          <GradeDetail
            key={`${selection.student}/${selection.lesson}`}
            detail={selectedDetail}
            theme={theme}
            onClose={() => setSelection(null)}
          />
        )}
      </main>
    </div>
  );
}
function Score({
  earned,
  maximum,
  submitted,
}: {
  earned: string;
  maximum: string;
  submitted?: boolean;
}) {
  if (Number(maximum) <= 0)
    return <span className="grade-score ungraded">Ungraded</span>;
  return (
    <span
      className={`grade-score ${Number(earned) >= Number(maximum) ? "full" : ""}`}
    >
      <span>
        {Number(earned)} / {Number(maximum)}
      </span>
      {submitted && <small>Submitted</small>}
    </span>
  );
}
function GradeDetail({
  detail,
  theme,
  onClose,
}: {
  detail: {
    student: { id: number; name: string; email: string };
    lesson: { id: number | null; title: string; kind: string };
    attempt: { started_at: string | null; submitted_at: string | null };
    activities: Work[];
  };
  theme: "light" | "dark";
  onClose: () => void;
}) {
  const [activityId, setActivityId] = useState(() =>
    (detail.lesson.id === null ? detail.activities[0] :
      detail.activities.find(part => part.lesson_id === detail.lesson.id))?.id || 0),
    [files, setFiles] = useState<Record<string, string>>({}),
    [selected, setSelected] = useState(""),
    [result, setResult] = useState<Record<string, unknown> | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [work, setWork] = useState<Partial<Work>>({}),
    [workLoading, setWorkLoading] = useState(false),
    [partQuery, setPartQuery] = useState(""),
    [lessonFilter, setLessonFilter] = useState(detail.lesson.id === null ? "" : String(detail.lesson.id)),
    [attempt, setAttempt] = useState("");
  const baseActivity = detail.activities.find((a) => a.id === activityId);
  const activity = baseActivity ? { ...baseActivity, ...work } : undefined;
  useEffect(() => { setAttempt(""); }, [activityId, detail.student.id]);
  useEffect(() => {
    if (!activityId) return;
    let cancelled = false;
    setWork({});
    setFiles({});
    setSelected("");
    setResult(null);
    setError("");
    setWorkLoading(true);
    api(
      `gradebook/work/?membership=${detail.student.id}&activity=${activityId}${attempt ? "&attempt=" + encodeURIComponent(attempt) : ""}`,
    )
      .then((next) => {
        if (cancelled) return;
        setWork(next);
        setFiles(next.files || {});
        setResult(next.attempt_result || null);
        setSelected(
          next.entrypoint || Object.keys(next.files || {}).find((x) => x.endsWith(".py")) ||
            Object.keys(next.files || {})[0] ||
            "",
        );
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setWorkLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activityId, detail.student.id, attempt]);
  async function execute(operation: "run" | "submit") {
    if (!activity || !selected) return;
    setBusy(true);
    setError("");
    try {
      const job = await api(`execute/${activity.revision}/`, {
        operation,
        files,
        entrypoint: selected,
        preview: true,
      });
      for (;;) {
        await new Promise((r) => setTimeout(r, 500));
        const state = await api(`jobs/${job.id}/`);
        if (["completed", "failed"].includes(state.status)) {
          setResult(state.result);
          break;
        }
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="grade-detail">
      <div className="grade-detail-head">
        <div>
          <span className="auth-kicker">{detail.lesson.title}</span>
          <h2>{detail.student.name || detail.student.email}</h2>
          <p>
            {detail.student.email}
            {detail.attempt.submitted_at &&
              ` · Quiz submitted ${new Date(detail.attempt.submitted_at).toLocaleString()}`}
          </p>
        </div>
        <button onClick={onClose}>Close</button>
      </div>
      <div className="student-review-layout">
        <aside className="review-activity-sidebar">
          <label>
            Assignment
            <select
              value={lessonFilter}
              disabled={busy}
              onChange={(e) => {
                const lesson = e.target.value;
                setLessonFilter(lesson);
                setPartQuery("");
                setAttempt("");
                setActivityId(detail.activities.find(part => !lesson || String(part.lesson_id) === lesson)?.id || 0);
              }}
            >
              {detail.lesson.id === null && <option value="">Entire course</option>}
              {[
                ...new Map(
                  detail.activities.map((a) => [a.lesson_id, a.lesson_title]),
                ).entries(),
              ].map(([id, title]) => (
                <option key={id} value={id}>
                  {title}
                </option>
              ))}
            </select>
          </label>
          <label>
            Find a part
            <input
              value={partQuery}
              onChange={(e) => setPartQuery(e.target.value)}
              placeholder="Part name"
            />
          </label>
          <div className="grade-activity-list">
            {detail.activities
              .filter(
                (a) =>
                  (!lessonFilter || String(a.lesson_id) === lessonFilter) &&
                  a.title.toLowerCase().includes(partQuery.toLowerCase()),
              )
              .map((a) => (
                <button
                  className={a.id === activityId ? "active" : ""}
                  key={a.id}
                  disabled={busy}
                  onClick={() => {setAttempt("");setActivityId(a.id);}}
                >
                  <span>
                    <small>{a.lesson_title}</small>
                    {a.title}
                  </span>
                  <Score earned={a.earned} maximum={a.maximum} />
                </button>
              ))}
          </div>
        </aside>
        <section className="review-activity-body">
          {workLoading && <p role="status">Loading saved work…</p>}
          {activity && (
            <div className="grade-work">
              <div className="grade-work-meta">
                <strong>{activity.title}</strong>
                <span>
                  {attempt ? `Recorded submission · ${work.attempt_status || "completed"}` : activity.saved_at
                    ? `Latest work saved ${new Date(activity.saved_at).toLocaleString()}`
                    : "No saved workspace"}
                </span>
              </div>
              <label className="submission-selector">Submission history
                <select aria-label="Submission history" value={attempt} disabled={busy || workLoading}
                  onChange={e=>setAttempt(e.target.value)}>
                  <option value="">Current workspace / latest answers</option>
                  {work.history?.map(item=><option key={item.id} value={item.id}>
                    Submission {item.number} · {new Date(item.submitted_at).toLocaleString()} · {item.status}
                    {item.score != null ? ` · ${item.score} / ${item.maximum}` : ""}{item.practice ? " · Practice" : ""}
                  </option>)}
                </select>
              </label>
              {attempt && !workLoading && <p className="review-note">Submitted {activity.submitted_at ? new Date(activity.submitted_at).toLocaleString() : ""} · Revision {activity.revision}. Edits below affect this review copy only.</p>}
              {workLoading ? null : selected ? (
                <>
                  <div className="review-workspace">
                    <div className="review-files">
                      {Object.keys(files).map((name) => (
                        <button
                          className={name === selected ? "active" : ""}
                          key={name}
                          onClick={() => setSelected(name)}
                        >
                          {name}
                        </button>
                      ))}
                    </div>
                    <div className="review-editor">
                      <Suspense fallback={<div>Loading editor…</div>}>
                        <EditorPane
                          value={files[selected] || ""}
                          path={`gradebook/${detail.student.id}/${activity.id}/${attempt || "current"}/${selected}`}
                          theme={theme}
                          disabled={busy}
                          onChange={(text) =>
                            setFiles({ ...files, [selected]: text })
                          }
                        />
                      </Suspense>
                    </div>
                    <div className="review-console">
                      <pre>
                        {busy
                          ? "Running…"
                          : String(
                              result?.error ||
                                (result?.workspace_files as Record<string,string> | undefined)?.["full_results.txt"] ||
                                result?.preview ||
                                result?.stdout ||
                                "No output.",
                            )}
                      </pre>
                      <div>
                        <button
                          disabled={busy || !selected.endsWith(".py")}
                          onClick={() => execute("run")}
                        >
                          <Play size={15} />
                          Run copy
                        </button>
                        <button
                          className="primary"
                          disabled={busy || !selected.endsWith(".py")}
                          onClick={() => execute("submit")}
                        >
                          <Check size={15} />
                          Submit copy
                        </button>
                      </div>
                    </div>
                  </div>
                  <p className="review-note">
                    This is a review copy. Running or submitting it does not
                    change the student’s saved work or grade.
                  </p>
                </>
              ) : (
                <div className="empty-state">
                  {activity.latest_response ? (
                    <>
                      <strong>{attempt ? "Submitted answers" : "Latest submitted answers"}</strong>
                      {attempt && result?.score != null && <p>Attempt score: {String(result.score)}</p>}
                      <dl className="submitted-answers">
                        {Object.entries(activity.latest_response).map(
                          ([question, answer]) => (
                            <div key={question}>
                              <dt>{question}</dt>
                              <dd>
                                {Array.isArray(answer)
                                  ? answer.join(", ")
                                  : String(answer)}
                              </dd>
                            </div>
                          ),
                        )}
                      </dl>
                    </>
                  ) : (
                    "No submitted answers or coding workspace for this activity."
                  )}
                </div>
              )}
              {error && <div className="notification error">{error}</div>}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
