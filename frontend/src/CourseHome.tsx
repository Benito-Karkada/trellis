import BrandLogo from "./BrandLogo";
import CourseHomeView from "./CourseHomeView";
import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  CheckCircle2,
  Search,
  X,
  ChevronDown,
  ClipboardList,
  Code2,
  Copy,
  FileText,
  GripVertical,
  ListChecks,
  Plus,
  Settings2,
  Trash2,
  Video,
  ArrowRight,
  Save,
  Undo2,
} from "lucide-react";
import { api } from "./api";
import LogoutButton from "./LogoutButton";
import UnitOverview from "./UnitOverview";
import { routeHref } from "./navigation";

type Activity = {
  id: number;
  title: string;
  status: string;
  earned_points: string;
  maximum_points: string;
  metadata?: { kind?: string };
};
type Lesson = {
  id: number;
  title: string;
  metadata?: {
    kind?: string;
    earned_points?: string;
    maximum_points?: string;
    activity_count?: number;
    completed_count?: number;
  };
  activities: Activity[];
};

const PART_KINDS: { value: string; label: string }[] = [
  { value: "reading", label: "Lecture text" },
  { value: "video", label: "Lecture video" },
  { value: "coding", label: "Coding exercise" },
  { value: "quiz", label: "Quiz question" },
];

export default function CourseHome({
  title,
  lessons,
  canManage,
  onOpen,
  onSettings,
  onGradebook,
  onRefresh,
  onSignOut,
  resume,
}: {
  title: string;
  lessons: Lesson[];
  canManage: boolean;
  onOpen: (lesson: number, activity: number | null) => void;
  onSettings: () => void;
  onGradebook: () => void;
  onRefresh: () => Promise<unknown>;
  onSignOut: () => void;
  resume?: {lesson_id:number;activity_id:number;lesson_title:string;activity_title:string;category:string} | null;
}) {
  const [editing, setEditing] = useState(false),
    [sectionTitle, setSectionTitle] = useState(""),
    [partTitles, setPartTitles] = useState<Record<number, string>>({}),
    [partKinds, setPartKinds] = useState<Record<number, string>>({}),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  type Draft = {version: string; lessons: Lesson[]; operations: Record<string, unknown>[]};
  const [draft, setDraft] = useState<Draft | null>(null);
  const draftRef = useRef<Draft | null>(null);
  const [history, setHistory] = useState<Draft[]>([]);
  const nextId = useRef(-1);
  const [notice, setNotice] = useState("");
  const [structureSearch, setStructureSearch] = useState("");
  const dirty = !!draft?.operations.length;
  function updateDraft(value: Draft | null) {draftRef.current = value;setDraft(value);}
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {event.preventDefault();event.returnValue = "";};
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function leave(action: () => void) {
    if (draftRef.current?.operations.length && !window.confirm("Discard unsaved course structure changes?")) return;
    action();
  }
  async function beginEditing() {
    setBusy(true);setError("");setNotice("");
    try {
      const data = await api("structure/draft/");
      updateDraft({...data, operations: []});setHistory([]);setEditing(true);
    } catch (error) {setError((error as Error).message);}
    finally {setBusy(false);}
  }
  async function saveStructure() {
    const current = draftRef.current;
    if (!current?.operations.length) return;
    setBusy(true);setError("");setNotice("");
    try {
      const data = await api("structure/save/", {base_version:current.version, operations:current.operations});
      updateDraft({...data, operations:[]});setHistory([]);setNotice("Course structure saved.");
      await onRefresh();
    } catch (error) {setError((error as Error).message);}
    finally {setBusy(false);}
  }
  async function act(endpoint: string, body: Record<string, unknown>) {
    const current = draftRef.current;
    if (!current || busy) return;
    setError("");setNotice("");
    const rows = structuredClone(current.lessons);
    const op = {...body, entity:endpoint.includes("lessons") ? "lesson" : "part"};
    const allocate = () => nextId.current--;
    const emptyPart = (id:number): Activity => ({id,title:String(body.title || "Untitled part").trim(),
      status:"",earned_points:"0",maximum_points:"0",metadata:{kind:String(body.kind || "reading")}});
    if (op.entity === "lesson") {
      const index = rows.findIndex(row => row.id === body.lesson_id);
      if (body.action === "create") {
        const id = allocate();Object.assign(op,{client_id:id});
        rows.push({id,title:String(body.title).trim(),metadata:{kind:"lesson"},activities:[]});
      } else if (body.action === "reorder") {
        const ids = body.lesson_ids as number[];
        const group = rows.filter(row => ids.includes(row.id));
        const ordered = ids.map(id => group.find(row => row.id === id)!);
        let next = 0;
        rows.forEach((row,i) => {if(ids.includes(row.id)) rows[i] = ordered[next++];});
      } else if (index >= 0) {
        if (body.action === "delete") rows.splice(index,1);
        if (body.action === "rename") rows[index].title = String(body.title);
        if (body.action === "copy") {
          const copy = structuredClone(rows[index]);const children:Record<string,number> = {};
          copy.id = allocate();copy.title = `Copy of ${copy.title}`;
          copy.activities.forEach(part => {const source = part.id;part.id = allocate();children[String(source)] = part.id;});
          Object.assign(op,{client_id:copy.id,client_part_ids:children});rows.push(copy);
        }
      }
    } else {
      const lesson = rows.find(row => row.id === body.lesson_id);
      if (!lesson) return;
      const index = lesson.activities.findIndex(part => part.id === body.activity_id);
      if (body.action === "create") {
        const id = allocate();Object.assign(op,{client_id:id});lesson.activities.push(emptyPart(id));
      } else if (body.action === "reorder") {
        lesson.activities = (body.activity_ids as number[]).map(id => lesson.activities.find(part => part.id === id)!);
      } else if (index >= 0) {
        if (body.action === "delete") lesson.activities.splice(index,1);
        if (body.action === "rename") lesson.activities[index].title = String(body.title);
        if (body.action === "copy") {
          const copy = structuredClone(lesson.activities[index]);copy.id = allocate();copy.title = `Copy of ${copy.title}`;
          Object.assign(op,{client_id:copy.id});lesson.activities.push(copy);
        }
      }
    }
    const last = current.operations[current.operations.length-1];
    const coalesced = body.action === "rename" && last?.action === "rename" && last.entity === op.entity
      && last.lesson_id === body.lesson_id && last.activity_id === body.activity_id;
    if (!coalesced) setHistory(previous => [...previous,current]);
    updateDraft({...current,lessons:rows,operations:coalesced ? [...current.operations.slice(0,-1),op] : [...current.operations,op]});
  }
  const visibleLessons = editing && draft ? draft.lessons : lessons;
  const courseLessons = visibleLessons.filter(l => l.metadata?.kind !== "programming_quiz"),
    quizzes = visibleLessons.filter(l => l.metadata?.kind === "programming_quiz");
  const open = (lesson:number, activity:number|null) => leave(() => onOpen(lesson,activity));
  if (!editing) {
  return <CourseHomeView title={title} lessons={courseLessons} quizzes={quizzes}
    canManage={canManage} resume={resume} busy={busy} error={error} notice={notice}
    onOpen={open} onGradebook={() => leave(onGradebook)} onSettings={() => leave(onSettings)}
    onEditStructure={beginEditing} onSignOut={onSignOut} />;
}
  return (
    <div className="home-shell">
      <header className="home-header">
        <div className="brand">
          <BrandLogo/>
        </div>
        <div className="home-actions">
          {canManage && (
            <>
              <button onClick={() => leave(onGradebook)}>
                <ClipboardList size={17} />
                Gradebook
              </button>
              <button onClick={() => leave(onSettings)}>
                <Settings2 size={17} />
                Course settings
              </button>
              <button
                className={editing ? "active" : ""}
                disabled={busy}
                onClick={() => editing ? leave(() => {setEditing(false);updateDraft(null);setHistory([]);setNotice("");setError("");}) : beginEditing()}
              >
                <BookOpen size={17} />
                {editing ? "Done editing" : "Edit course structure"}
              </button>
            </>
          )}

          <LogoutButton onConfirm={onSignOut}/>
        </div>
      </header>
      <main className="home-main">
        <section className="home-hero">
          <span>CS 1301</span>
          <h1>{title}</h1>
          <p>Lessons, problem sets, and programming assessments.</p>
        </section>
        {error && <div className="notification error" role="alert">{error}</div>}
        {notice && <div className="notification success" role="status">{notice}</div>}
        {editing && <section className="structure-draft-bar" aria-label="Course structure changes">
          <div><strong>{dirty ? `${draft!.operations.length} unsaved change${draft!.operations.length === 1 ? "" : "s"}` : "Course structure"}</strong>
            <p>Changes appear for students after you save. Undo restores your last draft change.</p></div>
          <div className="structure-draft-actions">
            <button disabled={busy || !history.length} onClick={() => {
              const previous = history[history.length-1];if(!previous) return;
              updateDraft(previous);setHistory(history.slice(0,-1));setError("");setNotice("");
            }}><Undo2 size={16}/>Undo</button>
            <button disabled={busy || !dirty} onClick={() => {
              if (!window.confirm("Discard all unsaved structure changes?")) return;
              beginEditing();
            }}>Discard changes</button>
            <button className="primary" disabled={busy || !dirty} onClick={saveStructure}><Save size={16}/>{busy ? "Saving…" : "Save changes"}</button>
          </div>
        </section>}
        {resume && !editing && <a className="resume-card" href={routeHref({page:"course",lessonId:resume.lesson_id,active:resume.activity_id,category:resume.category})}
          onClick={event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {event.preventDefault();onOpen(resume.lesson_id,resume.activity_id);} }}>
          <span className="resume-icon"><BookOpen size={25}/></span><div><small>Pick up where you left off</small><h2>{resume.activity_title}</h2><p>{resume.lesson_title}</p></div><span className="resume-continue">Continue <ArrowRight size={19}/></span>
        </a>}
        {editing && (
          <section className="structure-create">
            <div>
              <h2>Add a section</h2>
              <p>Create a new lesson or assignment in the course outline.</p>
            </div>
            <input
              value={sectionTitle}
              onChange={(e) => setSectionTitle(e.target.value)}
              placeholder="Section title"
            />
            <button
              className="primary"
              disabled={busy || !sectionTitle.trim()}
              onClick={async () => {
                await act("structure/lessons/", {
                  action: "create",
                  title: sectionTitle,
                });
                setSectionTitle("");
              }}
            >
              <Plus size={16} />
              Add section
            </button>
          </section>
        )}
        {editing && <div className="structure-search">
          <Search size={18} aria-hidden="true" />
          <input type="search" aria-label="Search section or part titles"
            placeholder="Search section or part titles…" value={structureSearch}
            onChange={event => setStructureSearch(event.target.value)} />
          {structureSearch && <button type="button" aria-label="Clear structure search"
            onClick={() => setStructureSearch("")}><X size={16} /></button>}
        </div>}
        {!editing ? <UnitOverview lessons={courseLessons} quizzes={quizzes} onOpen={open}/> : <><HomeGroup
          search={editing ? structureSearch : ""}
          title="Course"
          lessons={courseLessons}
          editing={editing}
          busy={busy}
          partTitles={partTitles}
          setPartTitles={setPartTitles}
          partKinds={partKinds}
          setPartKinds={setPartKinds}
          onOpen={open}
          act={act}
        />
        {!!quizzes.length && (
          <HomeGroup
            title="Programming quizzes"
            search={editing ? structureSearch : ""}
            lessons={quizzes}
            editing={editing}
            busy={busy}
            partTitles={partTitles}
            setPartTitles={setPartTitles}
            partKinds={partKinds}
            setPartKinds={setPartKinds}
            onOpen={open}
            act={act}
          />
        )}</>}
      </main>
    </div>
  );
}

function partIcon(kind?: string) {
  if (kind === "video") return <Video size={13} />;
  if (kind === "coding") return <Code2 size={13} />;
  if (kind === "quiz") return <ListChecks size={13} />;
  return <FileText size={13} />;
}

function HomeGroup({
  search,
  title,
  lessons,
  editing,
  busy,
  partTitles,
  setPartTitles,
  partKinds,
  setPartKinds,
  onOpen,
  act,
}: {
  title: string;
  search: string;
  lessons: Lesson[];
  editing: boolean;
  busy: boolean;
  partTitles: Record<number, string>;
  setPartTitles: (v: Record<number, string>) => void;
  partKinds: Record<number, string>;
  setPartKinds: (v: Record<number, string>) => void;
  onOpen: (lesson: number, activity: number | null) => void;
  act: (endpoint: string, body: Record<string, unknown>) => Promise<void>;
}) {
  const [dragLesson, setDragLesson] = useState<number | null>(null);
  const query = search.trim().toLocaleLowerCase();
  const matches = (lesson: Lesson) => !query || lesson.title.toLocaleLowerCase().includes(query)
    || lesson.activities.some(part => part.title.toLocaleLowerCase().includes(query));
  const matchingCount = lessons.filter(matches).length;
  const [expandedSections, setExpandedSections] = useState<Set<number>>(() => new Set());
  const allExpanded = lessons.length > 0 && lessons.every(lesson => expandedSections.has(lesson.id));
  function toggleParts(id: number) {
    setExpandedSections(current => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function dropLesson(target: Lesson) {
    if (dragLesson == null || dragLesson === target.id) {
      setDragLesson(null);
      return;
    }
    const ids = lessons.map((l) => l.id);
    const from = ids.indexOf(dragLesson),
      to = ids.indexOf(target.id);
    if (from === -1 || to === -1) {
      setDragLesson(null);
      return;
    }
    ids.splice(to, 0, ...ids.splice(from, 1));
    setDragLesson(null);
    act("structure/lessons/", { action: "reorder", lesson_ids: ids });
  }
  return (
    <section className="home-group">
      <div className="home-group-title">
        <h2>{title}</h2>
        <div className="structure-group-tools">
          <span role={query ? "status" : undefined}>{query ? `${matchingCount} matching section${matchingCount === 1 ? "" : "s"}` : `${lessons.length} sections`}</span>
          {editing && !query && lessons.length > 0 && (
            <button type="button" onClick={() => setExpandedSections(
              allExpanded ? new Set() : new Set(lessons.map(lesson => lesson.id))
            )}>{allExpanded ? "Collapse all parts" : "Expand all parts"}</button>
          )}
        </div>
      </div>
      {query && matchingCount === 0 && <p className="structure-search-empty">No matching section or part titles.</p>}
      <div className="home-grid">
        {lessons.map((lesson) => {
          const earned = Number(
              lesson.metadata?.earned_points ??
                lesson.activities.reduce(
                  (n, a) => n + Number(a.earned_points || 0),
                  0,
                ),
            ),
            maximum = Number(
              lesson.metadata?.maximum_points ??
                lesson.activities.reduce(
                  (n, a) => n + Number(a.maximum_points || 0),
                  0,
                ),
            ),
            complete =
              lesson.metadata?.completed_count ??
              lesson.activities.filter((a) => a.status === "completed").length,
            activityCount =
              editing ? lesson.activities.length : lesson.metadata?.activity_count ?? lesson.activities.length;
          return (
            <article
              className={`home-card ${dragLesson === lesson.id ? "dragging" : ""}`}
              key={lesson.id}
              hidden={!matches(lesson)}
              onDragOver={(e) => {
                if (editing && dragLesson != null) e.preventDefault();
              }}
              onDrop={(e) => {
                if (!editing || dragLesson == null) return;
                e.preventDefault();
                dropLesson(lesson);
              }}
            >
              {editing && lessons.length > 1 && (
                <span
                  className="drag-handle"
                  aria-label={`Reorder ${lesson.title}`}
                  title="Drag to reorder"
                  draggable
                  onDragStart={() => setDragLesson(lesson.id)}
                  onDragEnd={() => setDragLesson(null)}
                >
                  <GripVertical size={15} />
                </span>
              )}
              <a
                className="home-card-main"
                href={editing ? undefined : routeHref({page:"course",lessonId:lesson.id,active:lesson.activities[0]?.id || null,
                  category:(lesson.activities[0]?.metadata as {category?:string})?.category || "content"})}
                onClick={event => {if(editing){event.preventDefault();return;} if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
                  event.preventDefault();onOpen(lesson.id, lesson.activities[0]?.id || null);
                }}}
              >
                <span className="home-card-icon">
                  {lesson.metadata?.kind === "programming_quiz" ? (
                    <ClipboardList />
                  ) : (
                    <BookOpen />
                  )}
                </span>
                <div>
                  <small>
                    {lesson.metadata?.kind === "programming_quiz"
                      ? "Programming quiz"
                      : "Course section"}
                  </small>
                  <h3>{lesson.title}</h3>
                  <p>
                    {activityCount} parts ·{" "}
                    {maximum
                      ? `${earned} / ${maximum} points`
                      : `${complete} completed`}
                  </p>
                </div>
              </a>
              {editing && (
                <div className="home-card-edit">
                  <TitleEditor value={lesson.title} label={`Section title: ${lesson.title}`} disabled={busy}
                    onCommit={title => act("structure/lessons/", {action:"rename",lesson_id:lesson.id,title})}/>
                  <div>
                    <button
                      disabled={busy}
                      onClick={() =>
                        act("structure/lessons/", {
                          action: "copy",
                          lesson_id: lesson.id,
                        })
                      }
                    >
                      <Copy size={14} />
                      Copy section
                    </button>
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() =>
                        window.confirm(`Delete ${lesson.title}?`) &&
                        act("structure/lessons/", {
                          action: "delete",
                          lesson_id: lesson.id,
                        })
                      }
                    >
                      <Trash2 size={14} />
                      Delete
                    </button>
                  </div>
                  <div className="new-part">
                    <input
                      value={partTitles[lesson.id] || ""}
                      onChange={(e) =>
                        setPartTitles({
                          ...partTitles,
                          [lesson.id]: e.target.value,
                        })
                      }
                      placeholder="New part title"
                    />
                    <select
                      aria-label="New part type"
                      value={partKinds[lesson.id] || "reading"}
                      onChange={(e) =>
                        setPartKinds({
                          ...partKinds,
                          [lesson.id]: e.target.value,
                        })
                      }
                    >
                      {PART_KINDS.map((k) => (
                        <option value={k.value} key={k.value}>
                          {k.label}
                        </option>
                      ))}
                    </select>
                    <button
                      disabled={busy || !partTitles[lesson.id]?.trim()}
                      onClick={async () => {
                        await act("structure/activities/", {
                          action: "create",
                          lesson_id: lesson.id,
                          title: partTitles[lesson.id],
                          kind: partKinds[lesson.id] || "reading",
                        });
                        setPartTitles({ ...partTitles, [lesson.id]: "" });
                      }}
                    >
                      <Plus size={14} />
                      Add part
                    </button>
                  </div>
                  <div className="structure-parts-disclosure">
                    <button type="button" className="structure-parts-toggle"
                      aria-expanded={!!query || expandedSections.has(lesson.id)}
                      disabled={!!query}
                      aria-controls={`structure-parts-${lesson.id}`}
                      onClick={() => toggleParts(lesson.id)}>
                      <ChevronDown size={16} aria-hidden="true" />
                      <span>{query ? "Matching parts" : expandedSections.has(lesson.id) ? "Hide parts" : "Manage parts"}</span>
                      <span className="structure-parts-count">{query && !lesson.title.toLocaleLowerCase().includes(query)
                        ? lesson.activities.filter(part => part.title.toLocaleLowerCase().includes(query)).length
                        : lesson.activities.length}</span>
                    </button>
                    <div id={`structure-parts-${lesson.id}`} className="structure-parts-list"
                      hidden={!query && !expandedSections.has(lesson.id)}>
                      <PartList lesson={lesson} act={act} busy={busy}
                        search={lesson.title.toLocaleLowerCase().includes(query) ? "" : query} />
                      {lesson.activities.length === 0 && <p className="structure-parts-empty">No parts yet.</p>}
                    </div>
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PartList({
  search,
  lesson,
  act,
  busy,
}: {
  lesson: Lesson;
  search: string;
  busy: boolean;
  act: (endpoint: string, body: Record<string, unknown>) => Promise<void>;
}) {
  const [dragActivity, setDragActivity] = useState<number | null>(null);
  function dropActivity(target: Activity) {
    if (dragActivity == null || dragActivity === target.id) {
      setDragActivity(null);
      return;
    }
    const ids = lesson.activities.map((a) => a.id);
    const from = ids.indexOf(dragActivity),
      to = ids.indexOf(target.id);
    if (from === -1 || to === -1) {
      setDragActivity(null);
      return;
    }
    ids.splice(to, 0, ...ids.splice(from, 1));
    setDragActivity(null);
    act("structure/activities/", {
      action: "reorder",
      lesson_id: lesson.id,
      activity_ids: ids,
    });
  }
  return (
    <>
      {lesson.activities.map((activity) => (
        <div
          className={`part-edit ${dragActivity === activity.id ? "dragging" : ""}`}
          key={activity.id}
          hidden={!!search && !activity.title.toLocaleLowerCase().includes(search)}
          onDragOver={(e) => {
            if (dragActivity != null) e.preventDefault();
          }}
          onDrop={(e) => {
            if (dragActivity == null) return;
            e.preventDefault();
            dropActivity(activity);
          }}
        >
          {lesson.activities.length > 1 ? (
            <span
              className="drag-handle"
              aria-label={`Reorder ${activity.title}`}
              title="Drag to reorder"
              draggable
              onDragStart={() => setDragActivity(activity.id)}
              onDragEnd={() => setDragActivity(null)}
            >
              <GripVertical size={13} />
            </span>
          ) : (
            <span />
          )}
          <span>
            {partIcon(activity.metadata?.kind)}
            {activity.status === "completed" && <CheckCircle2 size={14} />}{" "}
            <TitleEditor value={activity.title} label={`Part title: ${activity.title}`} disabled={busy}
              onCommit={title => act("structure/activities/", {action:"rename",lesson_id:lesson.id,activity_id:activity.id,title})}/>
          </span>
          <button disabled={busy} aria-label={`Copy part: ${activity.title}`}
            onClick={() =>
              act("structure/activities/", {
                action: "copy",
                lesson_id: lesson.id,
                activity_id: activity.id,
              })
            }
          >
            <Copy size={13} />
          </button>
          <button disabled={busy} aria-label={`Delete part: ${activity.title}`}
            className="danger"
            onClick={() =>
              window.confirm(`Delete ${activity.title}?`) &&
              act("structure/activities/", {
                action: "delete",
                lesson_id: lesson.id,
                activity_id: activity.id,
              })
            }
          >
            <Trash2 size={13} />
          </button>
        </div>
      ))}
    </>
  );
}


function TitleEditor({value,label,disabled,onCommit}:{value:string;label:string;disabled?:boolean;onCommit:(value:string)=>Promise<void>}) {
  const focusValue = useRef(value);
  return <input className="structure-title-input" aria-label={label} value={value} maxLength={200} disabled={disabled}
    onFocus={() => {focusValue.current = value;}}
    onChange={event => onCommit(event.target.value)}
    onKeyDown={event => {
      if (event.key === "Enter") event.currentTarget.blur();
      if (event.key === "Escape") {onCommit(focusValue.current);event.currentTarget.blur();}
    }}/>
}
