import BrandLogo from "./BrandLogo";
import QuizNavigator from "./QuizNavigator";
import ProblemSetNavigator from "./ProblemSetNavigator";
import LogoutButton from "./LogoutButton";
import {newHonorlockBridge, type CompletionSignal} from "./honorlockBridge";
import {QuizAccessGate} from "./Honorlock";
import { useFocusTracking } from "./useFocusTracking";
import { useNavigation, routeHref, readRoute } from "./navigation";
import PaceBanner from "./PaceBanner";
import React, { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  Layers,
  Code2,
  FileText,
  FileCode2,
  CheckCircle2,
  Circle,
  CircleDot,
  Eye,
  Settings2,
  ChevronRight,
  ArrowLeft,
  ArrowRight,
  Play,
  Upload,
  Plus,
  Trash2,
  Pencil,
  Save,
  X,
  RotateCcw,
  LockKeyhole,
  Terminal,
  Users,
  Clock3,
  House,
  Braces,
} from "lucide-react";
import WorkspaceDivider from "./WorkspaceDivider";
import AuthScreen from "./AuthScreen";
import CourseSettings from "./CourseSettings";
import CourseHome from "./CourseHome";
import CourseLibrary from "./CourseLibrary";
import ContentBuilder from "./ContentBuilder";
import Gradebook from "./Gradebook";
import { api } from "./api";
const CodeVisualizer = lazy(() => import("./CodeVisualizer"));
const EditorPane = lazy(() => import("./EditorPane"));
type Node = {
  type: string;
  text?: string;
  children?: Node[];
  href?: string;
  src?: string;
  alt?: string;
  tag?: string;
};
type Block = {
  id: string;
  type: string;
  content?: Node[];
  prompt?: Node[];
  text?: string;
  choices?: { id: string; content: Node[] }[];
  entry_id?: string;
  partner_id?: string;
  uiconf_id?: string;
  widget_id?: string;
  url?: string;
  message?: string;
};
type Meta = {
  workspace_mode?: string;
  sandbox?: boolean;
  group?: string;
  category?: string;
  kind?: string;
  placeholder?: boolean;
  advanced?: boolean;
};
type Item = {
  id: number;
  title: string;
  metadata: Meta;
  status: string;
  earned_points: string;
  maximum_points: string;
};
type Lesson = {
  id: number;
  title: string;
  visibility?: string;
  metadata?: {
    kind?: string;
    exam_mode?: boolean;
    time_limit_minutes?: number;
    attempt_submitted?: boolean;
    attempt_started?: boolean;
    earned_points?: string;
    maximum_points?: string;
    activity_count?: number;
    completed_count?: number;
  };
  activities: Item[];
};
type Outline = {
  id: number;
  code: string;
  term: string;
  example: boolean;
  grading_feedback?: Record<string,string>;
  title: string;
  role: string;
  actual_role: string;
  student_view: boolean;
  lessons: Lesson[];
  resume?: {lesson_id:number;activity_id:number;lesson_title:string;activity_title:string;category:string} | null;
};
type File = { id?: number; path: string; visibility: string; text: string };
type Detail = {
  visualization_available?: boolean;
  ed_discussion_url?: string | null;
  reset_available?: boolean;
  native_practice?: boolean;
  solved_questions?: string[];
  native_review?: {responses:Record<string,string|string[]>;checks:Record<string,boolean>;feedback:Result["feedback"]};
  hints_available?: {general:boolean;questions:string[]};
  due_at?: string | null;
  practice?: boolean;
  title: string;
  lesson: number;
  revision: number;
  number: number;
  published_revision: number;
  content: { version: number; blocks: Block[] };
  files: File[];
  workspace?: Record<string, string>;
  metadata: Meta;
  maximum_points: string;
  earned_points: string;
  grading_enabled: boolean;
  grading?: Record<string, unknown>;
  history: { id: number; number: number; created_at: string }[];
  locks?: Record<string, string>;
};
type Result = {
  reset_available?: boolean;
  recorded_score?: string;
  solved_questions?: string[];
  practice?: boolean;
  feedback?: Record<string, { choice_id: string; content: Node[] }[]>;
  passed?: boolean;
  score?: string;
  maximum?: string;
  checks?: Record<string, boolean>;
  stdout?: string;
  preview?: string;
  full_output?: string;
  error?: string;
  execution_status?: string;
  stale?: boolean;
  locks?: Record<string, string>;
};
const safeUrl = (value = "") =>
  /^(https?:\/\/|\/api\/assets\/)/.test(value) ? value : "";
const safeImage = (value = "") =>
  safeUrl(value) ||
  (/^data:image\/(png|jpeg|gif|webp);base64,/.test(value) ? value : "");
const safeTags = new Set(
  "p div span h1 h2 h3 h4 h5 h6 ul ol li table thead tbody tfoot tr td th blockquote pre code strong b em i u s sub sup br hr".split(
    " ",
  ),
);
const feedbackText = (value = "") =>
  value.trim() === String.raw`\n`
    ? value
    : value.replace(/(?:\\n)+[ \t\r\n]*$/g, "");
const fileAccess = (path: string) =>
  path.startsWith("grader/")
    ? "grader"
    : path.startsWith("solutions/")
      ? "staff"
      : "student";
function Rich({
  nodes = [],
  feedback = false,
}: {
  nodes?: Node[];
  feedback?: boolean;
}): React.ReactNode {
  return nodes.map((n, i) => {
    if (n.type === "image")
      return safeImage(n.src) ? (
        <img key={i} src={safeImage(n.src)} alt={n.alt || ""} loading="lazy" />
      ) : (
        <span key={i}>[Image unavailable]</span>
      );
    if (n.type === "link")
      return (
        <a key={i} href={safeUrl(n.href)} target="_blank" rel="noreferrer">
          <Rich nodes={n.children} feedback={feedback} />
        </a>
      );
    if (n.type === "inline_code") return <code key={i}>{n.text}</code>;
    if (n.type === "line_break") return <br key={i} />;
    if (n.type === "strong")
      return (
        <strong key={i}>
          <Rich nodes={n.children} feedback={feedback} />
        </strong>
      );
    if (n.type === "emphasis")
      return (
        <em key={i}>
          <Rich nodes={n.children} feedback={feedback} />
        </em>
      );
    if (n.type === "element" && safeTags.has(n.tag || ""))
      return React.createElement(
        n.tag!,
        { key: i },
        ...(["br", "hr"].includes(n.tag!)
          ? []
          : [<Rich key="children" nodes={n.children} feedback={feedback} />]),
      );
    return (
      <React.Fragment key={i}>
        {feedback ? feedbackText(n.text) : n.text}
      </React.Fragment>
    );
  });
}
export default function App() {
  const { route, update: updateRoute, guard: navigationGuard } = useNavigation();
  const { page, courseId, lessonId, active, category, mode } = route;
  const setPage = (page: typeof route.page) => updateRoute({page});
  const setLessonId = (lessonId: number | null) => updateRoute({lessonId});
  const setActive = (active: number | null) => updateRoute({active});
  const setCategory = (category: string) => updateRoute({category});
  const setMode = (mode: typeof route.mode) => updateRoute({mode});
  const [booting, setBooting] = useState(true);
  const [outlineLoading, setOutlineLoading] = useState(false);
  const theme = "light" as const;
  const [split, setSplit] = useState(34);
  const [authenticated, setAuthenticated] = useState(false),
    [localLogin, setLocalLogin] = useState(false),
    [registrationOpen, setRegistrationOpen] = useState(false),
    [outline, setOutline] = useState<Outline | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null),
    [files, setFiles] = useState<File[]>([]),
    [selected, setSelected] = useState(""),
    [dirty, setDirty] = useState(false),
    [loading, setLoading] = useState(false);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [responses, setResponses] = useState<Record<string, string | string[]>>({}),
    [result, setResult] = useState<Result | null>(null);
  const [codeResult,setCodeResult]=useState<Result|null>(null);
  const [locks, setLocks] = useState<Record<string, string>>({}),
    [clock, setClock] = useState(() => Date.now());
  const [quizAttempt, setQuizAttempt] = useState<{
    attempt_id: number | null;
    expires_at: string | null;
    effective_minutes: string | null;
    expired: boolean;
    submitted: boolean;
    access_required?: boolean;
    honorlock_enabled?: boolean;
  } | null>(null);
  const [quizStatusLoaded, setQuizStatusLoaded] = useState(false);
  const honorlockBridge=useRef<ReturnType<typeof newHonorlockBridge>|null>(null);
  const [honorlockCompletion,setHonorlockCompletion]=useState<CompletionSignal|"idle"|"requesting">("idle");
  const [busy, setBusy] = useState(false),
    [lastOperation, setLastOperation] = useState<"run" | "submit" | null>(null),
    [editorTab, setEditorTab] = useState("Files"),
    [contentDraft, setContentDraft] = useState(""),
    [gradingDraft, setGradingDraft] = useState(""),
    [points, setPoints] = useState("1");
  const [advancedContent,setAdvancedContent]=useState(false);
  const [solvedQuestions,setSolvedQuestions]=useState<Set<string>>(new Set());
  const [reviewChoice,setReviewChoice]=useState<Record<string,string>>({});
  const [nativePractice,setNativePractice]=useState(false);
  const hintRequest=useRef(0);
  const [revealedHints,setRevealedHints]=useState<Record<string,Node[][]>>({});
  const [hintErrors,setHintErrors]=useState<Record<string,string>>({});
  const [hintLoading,setHintLoading]=useState<string|null>(null);
  const [resetOpen, setResetOpen] = useState(false),
    [fileDialog, setFileDialog] = useState<"new" | "rename" | null>(null),
    [filename, setFilename] = useState(""),
    [scroll, setScroll] = useState(0),
    [sidebar, setSidebar] = useState(() => window.innerWidth > 700);
  const input = useRef<HTMLInputElement>(null),
    loadSequence = useRef(0),
    pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedback = {success_title:"Well done!",success_body:"Your submission earned full credit. Your score has been updated.",failure_title:"Not quite yet",failure_body:"Open full_results.txt to compare your answer with the expected results.",...outline?.grading_feedback};
  const preview = mode === "preview",
    config = mode === "config",
    canManage = ["instructor", "head_ta", "ta"].includes(
      outline?.actual_role || outline?.role || "",
    ),
    staff = canManage && !outline?.student_view;
  useFocusTracking(lessonId, active, page === "course" && !preview && !config && outline?.actual_role === "student");
  const lesson = outline?.lessons.find((l) => l.id === lessonId),
    quizCompleted = !!(lesson?.metadata?.attempt_submitted || quizAttempt?.submitted || quizAttempt?.expired) && !staff,
    items =
      (lesson?.metadata?.kind === "programming_quiz" ? lesson.activities : lesson?.activities.filter(
        (a) => (a.metadata.category || "content") === category,
      )) || [];
  const index = items.findIndex((a) => a.id === active),
    completed = items.filter((a) => a.status === "completed").length;
  const earnedPoints = lesson?.metadata?.kind === "programming_quiz"
      ? Number(lesson?.metadata?.earned_points || 0)
      : items.reduce((sum, item) => sum + Number(item.earned_points || 0), 0),
    maximumPoints = lesson?.metadata?.kind === "programming_quiz"
      ? Number(lesson?.metadata?.maximum_points || 0)
      : items.reduce((sum, item) => sum + Number(item.maximum_points || 0), 0);
  const contentItems = lesson?.activities.filter(a => (a.metadata.category || "content") === "content") || [];
  const psetItems = lesson?.activities.filter(a => a.metadata.category === "problem_set") || [];
  const psetQuestions = psetItems.filter(a => Number(a.maximum_points)>0 || a.metadata.kind === "coding");
  const groups = [...new Set(contentItems.map(a => a.metadata.group || "Activities"))];
  const chapterSequence = lesson?.metadata?.kind === "programming_quiz" ? items : [...contentItems,...psetItems];
  const chapterIndex = chapterSequence.findIndex(a=>a.id===active);

  const sandbox = !!detail?.metadata.sandbox || detail?.metadata.workspace_mode === "sandbox";
  const coding = detail?.content.blocks.some((b) => b.type === "coding"),
    placeholder = detail?.metadata.placeholder,
    current = files.find((f) => f.path === selected);
  const questions =
    detail?.content.blocks.filter((b) =>
      ["multiple_choice", "select_all", "fill_blank", "numeric"].includes(
        b.type,
      ),
    ) || [];
  const executionResult=questions.length ? codeResult : result;
  useEffect(()=>{document.title=outline && page!=="courses" ? `${outline.code || outline.title} · Trellis` : "Trellis";},[outline?.id,outline?.title,outline?.code,page]);
  const refreshOutline = async () => {
    const data = await api("outline/");
    if (readRoute().courseId === data.id || !readRoute().courseId) setOutline(data);
    return data as Outline;
  };
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);
  useEffect(() => {
    api("session/")
      .then((s) => {
        setAuthenticated(s.authenticated);
        setLocalLogin(s.local_login);
        setRegistrationOpen(s.registration_open === true);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBooting(false));
  }, []);
  useEffect(() => {
    if (!authenticated || page === "courses") return;
    let current=true;
    loadSequence.current++;
    if(pollTimer.current)clearTimeout(pollTimer.current);
    setOutline(null);setDetail(null);setFiles([]);setResult(null);setCodeResult(null);
    setResponses({});setDirty(false);setQuizAttempt(null);setQuizStatusLoaded(false);
    setError("");setNotice("");setOutlineLoading(true);
    api("outline/").then(data=>{
      if(!current)return;
      setOutline(data);
      if(!courseId)updateRoute({courseId:data.id});
    }).catch(e=>{if(current)setError(e.message);})
      .finally(()=>{if(current)setOutlineLoading(false);});
    return()=>{current=false;};
  }, [authenticated, courseId, page === "courses"]);
  useEffect(()=>{
    if(page!=="course"||!authenticated||!lessonId||outline?.actual_role!=="student")return;
    api(`assignments/${lessonId}/open/`,{}).catch(()=>{});
  },[page,lessonId,authenticated,outline?.actual_role]);
  async function load(clear = true, preserveNative = false) {
    if (!active || page !== "course" || !authenticated || !outline) return;
    if (!outline.lessons.some(l=>l.activities.some(a=>a.id===active))) {setDetail(null);setLoading(false);return;}
    const id = ++loadSequence.current;
    if (clear) {
      setLoading(true);
      setDetail(null);
      setFiles([]);
      setResult(null);setCodeResult(null);
      setResponses({});
      setError("");
      setNotice("");
      setLocks({});
      hintRequest.current++;setRevealedHints({});setHintErrors({});setHintLoading(null);setSolvedQuestions(new Set());setReviewChoice({});setNativePractice(false);
    }
    try {
      const d: Detail = await api(`studio/${active}/?mode=${mode}`);
      const entries: File[] = config
        ? await Promise.all(
            d.files.map(async (f) => ({
              ...f,
              text: (await api(`files/${f.id}/?mode=config`)).text,
            })),
          )
        : Object.entries(d.workspace || {}).map(([path, text]) => ({
            path,
            text,
            visibility: "student",
          }));
      if (id !== loadSequence.current) return;
      setDetail(d);
      setNativePractice(!!d.native_practice);
      setSolvedQuestions(new Set(d.solved_questions||[]));
      if(d.native_review && !preserveNative){setResponses(d.native_review.responses);setResult({checks:d.native_review.checks,feedback:d.native_review.feedback});}
      setFiles(entries);
      setLocks(d.locks || {});
      setSelected((old) =>
        entries.some((f) => f.path === old)
          ? old
          : entries.find(
              (f) =>
                f.path.endsWith(".py") && !f.path.includes("sample_answer"),
            )?.path ||
            entries[0]?.path ||
            "",
      );
      setPoints(d.maximum_points);
      setContentDraft(JSON.stringify(d.content, null, 2));
      setGradingDraft(JSON.stringify(d.grading || {}, null, 2));
      setDirty(false);
      if (mode === "student") {
        await api(`viewed/${active}/`, {});
        await refreshOutline();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      if (id === loadSequence.current) setLoading(false);
    }
  }
  useEffect(() => {
    if (page !== "course" || !authenticated || !outline) { loadSequence.current += 1; return; }
    load();
    setEditorTab("Files");
    window.scrollTo(0, 0);
  }, [active, mode, page, authenticated, outline?.role, outline?.id]);
  useEffect(() => {
    const update = () => {
      const size = document.documentElement.scrollHeight - window.innerHeight;
      setScroll(size > 0 ? window.scrollY / size : 1);
    };
    window.addEventListener("scroll", update);
    return () => window.removeEventListener("scroll", update);
  }, []);
  useEffect(
    () => () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    },
    [],
  );
  useEffect(() => {
    if (!Object.keys(locks).length) return;
    setClock(Date.now());
    const id = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(id);
  }, [locks]);
  useEffect(() => {
    if (page !== "course" || lesson?.metadata?.kind !== "programming_quiz") {
      setQuizAttempt(null);
      setQuizStatusLoaded(false);
      return;
    }
    let current=true;
    setQuizStatusLoaded(false);
    api(`quizzes/${lesson.id}/status/`)
      .then(data=>{if(current)setQuizAttempt(data);})
      .catch((e) => {if(current)setError(e.message);})
      .finally(() => {if(current)setQuizStatusLoaded(true);});
    return()=>{current=false;};
  }, [lessonId, page, lesson?.metadata?.kind]);
  useEffect(() => {
    if (!quizAttempt?.expires_at) return;
    const id = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(id);
  }, [quizAttempt?.expires_at]);
  function remainingSeconds(qid: string) {
    const until = locks[qid];
    return until
      ? Math.max(0, Math.ceil((new Date(until).getTime() - clock) / 1000))
      : 0;
  }
  function formatCountdown(total: number) {
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  }
  const quizSeconds = quizAttempt?.expires_at
    ? Math.max(
        0,
        Math.ceil((new Date(quizAttempt.expires_at).getTime() - clock) / 1000),
      )
    : null;
  const examActive = !!(
    lesson?.metadata?.exam_mode &&
    (!canManage || outline?.student_view) && !config && !preview &&
    quizAttempt?.attempt_id &&
    !quizAttempt.submitted && !quizAttempt.access_required && !quizAttempt.expired
  );
  useEffect(() => {
    if (!examActive) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [examActive]);
  useEffect(()=>{
    if(quizSeconds!==0 || staff || quizAttempt?.expired)return;
    setQuizAttempt(old=>old?{...old,expired:true}:old);
    void refreshOutline();
  },[quizSeconds,staff,quizAttempt?.expired]);
  useEffect(()=>{
    honorlockBridge.current=null;
    setHonorlockCompletion("idle");
  },[lessonId,authenticated,quizAttempt?.attempt_id]);
  useEffect(()=>{
    if(!examActive || !quizAttempt?.honorlock_enabled)return;
    if(!honorlockBridge.current)honorlockBridge.current=newHonorlockBridge();
    void honorlockBridge.current.prepare();
  },[examActive,quizAttempt?.honorlock_enabled,lessonId]);
  const leave = () =>
    !examActive &&
    !busy &&
    (!dirty || window.confirm("Discard unsaved changes?"));
  navigationGuard.current = leave;
  async function beginQuiz(password?:string) {
    if (!lesson || busy) return;
    setBusy(true);setError("");
    try {
      const started=await api(`quizzes/${lesson.id}/start/`, password===undefined?{}:{password});
      setClock(Date.now());
      setQuizAttempt(started);
      const updated = await refreshOutline();
      const opened = updated.lessons.find((row) => row.id === lesson.id);
      setActive(opened?.activities[0]?.id || null);
      setCategory(opened?.activities[0]?.metadata.category || "content");
    } catch (e) {
      setError((e as Error).message);
    } finally {setBusy(false);}
  }
  async function finishQuiz() {
    if (
      !lesson || busy ||
      !window.confirm(
        "Submit this programming quiz and end the exam? You will not be able to change your answers afterward.",
      )
    )
      return;
    setBusy(true);
    try {
      const data = await api(`quizzes/${lesson.id}/finish/`, {});
      // Send only after Trellis has committed the final submission successfully.
      if(quizAttempt?.honorlock_enabled){
        const bridge=honorlockBridge.current || newHonorlockBridge();
        honorlockBridge.current=bridge;setHonorlockCompletion("requesting");
        void bridge.notifySubmitted().then(result=>{if(honorlockBridge.current===bridge)setHonorlockCompletion(result);});
      }
      setQuizAttempt((old) => (old ? { ...old, submitted: true } : old));
      setNotice(
        `Quiz submitted · ${data.earned_points} / ${data.maximum_points} points.`,
      );
      await refreshOutline();
    } catch (e) {
      setError((e as Error).message);
    } finally {setBusy(false);}
  }
  async function toggleStudentView() {
    if (!canManage || busy || (dirty && !window.confirm("Discard unsaved changes?"))) return;
    try {
    const enabled = !outline?.student_view;
    await api("student-view/", { enabled });
    const data = await refreshOutline();
    setMode("student");
    const current = data.lessons.find((l) => l.id === lessonId);
    if (page === "course" && !current) {
      setDetail(null);setFiles([]);
      setNotice("This section is not available in student view. Exit student view to continue editing it.");
    }
    // Keep the route even when a closed quiz hides its question list.
    setQuizStatusLoaded(false);
    if (current?.metadata?.kind === "programming_quiz") {
      try {setQuizAttempt(await api(`quizzes/${current.id}/status/`));}
      catch {setQuizAttempt(null);}
      finally {setQuizStatusLoaded(true);}
    }
    } catch(e) {setError((e as Error).message);}
  }
  async function resetQuizTest() {
    if (!lesson || !canManage || !window.confirm("Reset your own quiz attempt, saved work and score? Student attempts will not change.")) return;
    setBusy(true);
    try {
      await api(`quizzes/${lesson.id}/reset-test/`, {});
      if (pollTimer.current) clearTimeout(pollTimer.current);
      setQuizAttempt(null);
      setQuizStatusLoaded(true);
      setDetail(null);setFiles([]);setResult(null);setDirty(false);
      setActive(null);
      await refreshOutline();
      setNotice("Your student-view quiz attempt was reset. You can begin it again.");
    } catch(e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function navigate(id: number) {
    if(busy || id===active)return;
    const question=lesson?.activities.find(item=>item.id===id);
    if(lesson?.metadata?.kind === "programming_quiz" && !staff && !preview && !config){
      // The course remains locked during an exam, but its own questions must be reachable.
      if(!question || quizCompleted || quizAttempt?.access_required)return;
      if(dirty && detail){
        setBusy(true);setError("");
        try{
          await api(`workspaces/${detail.revision}/`,{files:Object.fromEntries(files.map(file=>[file.path,file.text]))});
          setDirty(false);
        }catch(error){setError((error as Error).message);return;}
        finally{setBusy(false);}
      }
      setCategory(question.metadata.category || "content");setActive(id);
    }else if(leave()){
      const target=lesson?.activities.find(a=>a.id===id);
      if(target)setCategory(target.metadata.category || "content");
      setActive(id);
    }
  }
  function changeMode(value: typeof mode) {
    if (leave()) setMode(value);
  }
  function selectLesson(id: number) {
    if (!leave()) return;
    const next = outline?.lessons.find((l) => l.id === id);
    setLessonId(id);
    setCategory(next?.activities[0]?.metadata.category || "content");
    setActive(next?.activities[0]?.id || null);
  }
  function selectCategory(value: string) {
    if (!leave()) return;
    setCategory(value);
    setActive(
      lesson?.activities.find(
        (a) => (a.metadata.category || "content") === value,
      )?.id || null,
    );
  }
  async function save() {
    if (!detail) return;
    try {
      if (config) {
        const grading = { ...JSON.parse(gradingDraft), maximum_points: points };
        await api(`studio/${active}/edit/`, {
          base_revision: detail.revision,
          content: JSON.parse(contentDraft),
          grading,
          files,
        });
        await load(false);
      } else if (!preview)
        await api(`workspaces/${detail.revision}/`, {
          files: Object.fromEntries(files.map((f) => [f.path, f.text])),
        });
      setDirty(false);
      setNotice(
        config
          ? "Draft saved."
          : preview
            ? "Changes kept in this preview."
            : "Saved.",
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function publish() {
    try {
      await api(`studio/${active}/edit/`, {
        action: "publish",
        base_revision: detail?.revision,
      });
      await load(false);
      setNotice("Published.");
      await refreshOutline();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function reset() {
    setResetOpen(false);
    if (!detail) return;
    try {
      if (!preview)
        await api(`workspaces/${detail.revision}/`, { action: "reset" });
      await load(false, questions.length > 0);
      setCodeResult(null);
      if(!questions.length){setResult(null);setResponses({});}
      setLastOperation(null);
      setNotice("Original files restored.");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function revealHints(questionId:string,choiceId?:string){
    if (!detail) return;
    if (!choiceId && revealedHints[questionId] && !reviewChoice[questionId]) {
      setRevealedHints(old=>{const next={...old};delete next[questionId];return next;});return;
    }
    const request=++hintRequest.current;
    const revision=detail.revision;setHintLoading(questionId);setHintErrors(old=>({...old,[questionId]:""}));
    if(choiceId)setReviewChoice(old=>({...old,[questionId]:choiceId}));
    else setReviewChoice(old=>{const next={...old};delete next[questionId];return next;});
    try {
      const data=await api(`hints/${revision}/`,{question_id:questionId,kind:choiceId?"choice":"general",choice_id:choiceId,preview:preview||config});
      if(request===hintRequest.current)setRevealedHints(old=>({...old,[questionId]:data.hints}));
    } catch(e){if(request===hintRequest.current)setHintErrors(old=>({...old,[questionId]:(e as Error).message}));}
    finally{if(request===hintRequest.current)setHintLoading(null);}
  }
  function clearQuestionHints(questionId:string){
    hintRequest.current++;setHintLoading(null);
    setRevealedHints(old=>{const next={...old};delete next[questionId];return next;});
    setHintErrors(old=>({...old,[questionId]:""}));
  }
  function clearQuestionFeedback(questionId:string){
    setResult(old=>{
      if(!old)return null;
      const checks={...old.checks},feedback={...old.feedback};
      delete checks[questionId];delete feedback[questionId];
      return {...old,checks,feedback};
    });
  }
  async function resetNative() {
    if (!detail) return;
    setBusy(true);setError("");
    try {
      if (!preview && !config) await api(`reset-native/${detail.revision}/`, {});
      hintRequest.current++;setRevealedHints({});setHintErrors({});setHintLoading(null);
      setResponses({});setResult(null);setSolvedQuestions(new Set());setReviewChoice({});setLocks({});
      setNativePractice(true);setDetail(old=>old?{...old,reset_available:false,native_practice:true,native_review:undefined,solved_questions:[]}:old);
      setNotice("Exercise reset for practice. Your earned points are unchanged.");
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function submitNative() {
    if (!detail) return;
    setBusy(true);
    setError("");
    try {
      const data: Result = await api(`submit-native/${detail.revision}/`, {
        responses,
        preview: preview || config,
      });
      setResult({...data,practice:data.practice||nativePractice});
      if (!preview && !config && data.recorded_score !== undefined) setDetail(old=>old?{...old,earned_points:data.recorded_score!,reset_available:data.reset_available}:old);
      setSolvedQuestions(old=>new Set([...old,...(data.solved_questions||Object.entries(data.checks||{}).filter(([,correct])=>correct).map(([qid])=>qid))]));
      setLocks(data.locks || {});
      if (!preview && !config) await refreshOutline();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const executionInFlight = useRef(false);
  const [executionPhase, setExecutionPhase] = useState("Queued… Waiting for the runner.");
  async function execute(operation: "run" | "submit") {
    if (!detail || executionInFlight.current) return;
    executionInFlight.current = true;
    setExecutionPhase("Queued… Waiting for the runner.");
    setBusy(true);
    setError("");
    setLastOperation(operation);
    if(questions.length)setCodeResult(null);else setResult(null);
    try {
      const job = await api(`execute/${detail.revision}/`, {
        operation,
        files: Object.fromEntries(files.map((f) => [f.path, f.text])),
        entrypoint: selected,
        preview,
      });
      setDirty(false);
      const poll = async () => {
        try {
          const state = await api(`jobs/${job.id}/`);
          setExecutionPhase(state.status === "running" ? "Running your code…" : "Queued… Waiting for the runner.");
          if (["completed", "failed"].includes(state.status)) {
            executionInFlight.current = false;
            if(questions.length)setCodeResult(state.result);else setResult(state.result);
            setBusy(false);
            if (!preview) {
              await load(false, questions.length > 0);
              await refreshOutline();
            } else if (state.result.workspace_files) {
              setFiles((old) =>
                old.map((f) =>
                  state.result.workspace_files[f.path] !== undefined
                    ? { ...f, text: state.result.workspace_files[f.path] }
                    : f,
                ),
              );
            }
            return;
          }
          pollTimer.current = setTimeout(poll, 700);
        } catch (e) {
          executionInFlight.current = false;
          setError((e as Error).message);
          setBusy(false);
        }
      };
      pollTimer.current = setTimeout(poll, 350);
    } catch (e) {
      executionInFlight.current = false;
          setError((e as Error).message);
      setBusy(false);
    }
  }
  function editFilename() {
    const name = filename.trim();
    if (
      !name ||
      name.startsWith("/") ||
      name.includes("\\") ||
      name.split("/").some((x) => !x || x === ".." || x === ".") ||
      files.some((f) => f.path === name)
    ) {
      setError("Choose a unique relative filename.");
      return;
    }
    setFiles(
      fileDialog === "rename"
        ? files.map((f) =>
            f.path === selected
              ? { ...f, path: name, visibility: fileAccess(name) }
              : f,
          )
        : [...files, { path: name, text: "", visibility: fileAccess(name) }],
    );
    setSelected(name);
    setDirty(true);
    setFileDialog(null);
  }
  function renderBlock(block: Block) {
    if (["paragraph", "document"].includes(block.type))
      return (
        <div className="course-document" key={block.id}>
          <Rich nodes={block.content} />
        </div>
      );
    if (block.type === "code")
      return (
        <pre className="reading-code" key={block.id}>
          {block.text}
        </pre>
      );
    if (block.type === "coding")
      return (
        <div className="course-document" key={block.id}>
          <Rich nodes={block.prompt} />
        </div>
      );
    if (block.type === "kaltura") {
      const params = new URLSearchParams({
        iframeembed: "true",
        entry_id: block.entry_id || "",
      });
      params.set(
        "config[plugins]",
        JSON.stringify({
          transcript: {
            disable: false,
            position: "right",
            expandOnFirstPlay: false,
          },
          uiManagers: {},
          kalturaCuepoints: {},
        }),
      );
      if (block.widget_id)
        params.set(
          "config[provider]",
          JSON.stringify({ widgetId: block.widget_id }),
        );
      return (
        <iframe
          key={block.id}
          className="course-video"
          title={detail?.title}
          src={`https://cdnapisec.kaltura.com/p/${block.partner_id}/embedPlaykitJs/uiconf_id/${block.uiconf_id}?${params}`}
          allow="autoplay; fullscreen; encrypted-media"
          allowFullScreen
        />
      );
    }
    if (block.type === "video")
      return (
        <video
          className="course-video"
          controls
          preload="metadata"
          src={safeUrl(block.url)}
          key={block.id}
        />
      );
    if (block.type === "placeholder")
      return (
        <div className="empty-state" key={block.id}>
          {block.message}
        </div>
      );
    if (!questions.includes(block)) return null;
    const seconds = remainingSeconds(block.id),
      locked = seconds > 0,
      solved = solvedQuestions.has(block.id);
    return (
      <fieldset className="question" key={block.id}>
        <legend>
          <Rich nodes={block.prompt} />
        </legend>
        {block.choices ? (
          block.choices.map((choice) => {
            const values = responses[block.id];
            const checked = Array.isArray(values)
              ? values.includes(choice.id)
              : values === choice.id;
            if(solved)return <button type="button" key={choice.id} className={`choice-review ${checked?"chosen":""} ${reviewChoice[block.id]===choice.id?"inspected":""}`} aria-pressed={reviewChoice[block.id]===choice.id} disabled={busy||hintLoading!==null} onClick={()=>revealHints(block.id,choice.id)}>{checked?<CheckCircle2 size={18}/>:<Circle size={18}/>}<span className="choice-content"><Rich nodes={choice.content}/></span><small>Explanation</small></button>;
            return (
              <label key={choice.id} className={checked ? "chosen" : ""}>
                <input
                  type={block.type === "select_all" ? "checkbox" : "radio"}
                  name={block.id}
                  checked={checked}
                  disabled={busy || locked}
                  onChange={() => {
                    clearQuestionHints(block.id);
                    setResponses({
                      ...responses,
                      [block.id]:
                        block.type === "select_all"
                          ? checked
                            ? (Array.isArray(values) ? values : []).filter(
                                (v) => v !== choice.id,
                              )
                            : [
                                ...(Array.isArray(values) ? values : []),
                                choice.id,
                              ]
                          : choice.id,
                    });
                    clearQuestionFeedback(block.id);
                  }}
                />
                <span className="choice-content"><Rich nodes={choice.content} /></span>
              </label>
            );
          })
        ) : (
          <input
            className="answer-input"
            aria-label="Your answer"
            value={(responses[block.id] as string) || ""}
            disabled={busy || locked}
            onChange={(e) => {
              clearQuestionHints(block.id);
              setResponses({ ...responses, [block.id]: e.target.value });
              clearQuestionFeedback(block.id);
            }}
          />
        )}
        {solved && block.choices && <p className="choice-review-note">Correct. Click any answer to read its explanation.</p>}
        {(detail?.hints_available?.general || revealedHints[block.id] || hintErrors[block.id]) && <div className="question-hints">
          {detail?.hints_available?.general && <button type="button" className="hint-button" aria-expanded={!!revealedHints[block.id]&&!reviewChoice[block.id]} aria-controls={`hints-${block.id}`} disabled={hintLoading!==null} onClick={()=>revealHints(block.id)}>{hintLoading===block.id?"Loading hints…":revealedHints[block.id]&&!reviewChoice[block.id]?"Hide hints":"Show hints"}</button>}
          {hintErrors[block.id]&&<p role="alert">{hintErrors[block.id]}</p>}
          {revealedHints[block.id]&&<div id={`hints-${block.id}`} className="revealed-hints" role="region" aria-label={reviewChoice[block.id]?"Answer explanation":"Question hints"}>{revealedHints[block.id].length?revealedHints[block.id].map((nodes,i)=><div className="course-document" key={i}><Rich nodes={nodes} feedback/></div>):<p>No explanation was provided for this answer.</p>}</div>}
        </div>}
        {!revealedHints[block.id] && result?.feedback?.[block.id]?.map((hint,i)=><div className="answer-feedback course-document" key={i}><Rich nodes={hint.content} feedback/></div>)}
        {result?.checks && block.id in result.checks && <p className={result.checks[block.id]?"correct-answer":"incorrect-answer"}>{result.checks[block.id]?"Correct":"Not yet correct"}</p>}
        {locked&&<p className="cooldown-message">Try again in {formatCountdown(seconds)}</p>}
      </fieldset>
    );
  }
  function clearAccountView() {
    loadSequence.current += 1;
    if (pollTimer.current) clearTimeout(pollTimer.current);
    updateRoute({page:"courses",courseId:null,lessonId:null,active:null,category:"content",mode:"student"});
    setOutline(null);
    setDetail(null);setFiles([]);setSelected("");
    setResult(null);setResponses({});setLocks({});
    hintRequest.current++;setRevealedHints({});setHintErrors({});setHintLoading(null);setSolvedQuestions(new Set());setReviewChoice({});setNativePractice(false);
    setQuizAttempt(null);setQuizStatusLoaded(false);
    setDirty(false);setBusy(false);setLoading(false);
    setError("");setNotice("");setLastOperation(null);
  }
  const authenticatedNow = () => {
    const destination=readRoute();
    clearAccountView();
    if(destination.courseId || destination.page==="course" || destination.page==="visualizer")updateRoute(destination);
    setOutlineLoading(true);
    setAuthenticated(true);
  };
  async function signOut() {
    try {
      await api("auth/logout/", {});
      clearAccountView();
      setAuthenticated(false);
    } catch (e) { setError((e as Error).message); }
  }
  if (booting || (authenticated && page!=="courses" && (outlineLoading || !outline || (!!courseId && outline.id!==courseId))))
    return <div className="startup-shell"><div className="brand"><BrandLogo/></div><main role="status" aria-live="polite"><span className="startup-spinner"/><h1>{error ? "Couldn’t load your course" : "Opening your course"}</h1>{error ? <><p>{error}</p><button className="primary" onClick={() => window.location.reload()}>Try again</button><button onClick={()=>updateRoute({page:"courses",courseId:null})}>All courses</button></> : <p>Getting your lessons and progress.</p>}</main></div>;
  if (!authenticated)
    return (
      <AuthScreen
        onAuthenticated={authenticatedNow}
        localLogin={localLogin}
        registrationOpen={registrationOpen}
      />
    );
  if (page === "courses")
    return <CourseLibrary onSignOut={signOut} onOpen={id=>{if(leave())updateRoute({page:"home",courseId:id,lessonId:null,active:null,category:"content",mode:"student"});}}/>;
  if (page === "settings" && outline)
    return (
      <CourseSettings
        course={outline.title}
        onBack={() => {
          setPage("home");
          refreshOutline();
        }}
        theme={theme}
      />
    );
  if (page === "gradebook")
    return <Gradebook courseLabel={outline?.code || outline?.title || "Course"} theme={theme} onBack={() => setPage("home")} />;
  if (page === "visualizer")
    return <Suspense fallback={<div className="startup-shell" role="status">Opening code visualizer…</div>}><CodeVisualizer activity={active} onBack={()=>setPage(active && lessonId?"course":"home")}/></Suspense>;
  if (page === "home" && outline)
    return (
      <CourseHome
        title={outline.title}
        code={outline.code}
        example={outline.example}
        term={outline.term}
        onCourses={()=>{if(leave())updateRoute({page:"courses",courseId:null,lessonId:null,active:null});}}
        lessons={outline.lessons}
        resume={outline.resume}
        canManage={staff}
        onSignOut={signOut}
        onVisualize={() => updateRoute({page:"visualizer",active:null,lessonId:null})}
        onRefresh={refreshOutline}
        onSettings={() => setPage("settings")}
        onGradebook={() => setPage("gradebook")}
        onOpen={(nextLesson, nextActivity) => {
          const next = outline.lessons.find((row) => row.id === nextLesson);
          setLessonId(nextLesson);
          setCategory(next?.activities.find(a => a.id === nextActivity)?.metadata.category || next?.activities[0]?.metadata.category || "content");
          setMode("student");
          setActive(nextActivity);
          setPage("course");
        }}
      />
    );
  return (
    <div
      className={`app ${preview || !sidebar ? "collapsed" : ""} ${examActive ? "exam-active" : ""} ${quizCompleted ? "quiz-complete" : ""}`}
      onCopy={(e) => {
        if (examActive) e.preventDefault();
      }}
      onPaste={(e) => {
        if (examActive) e.preventDefault();
      }}
      onCut={(e) => {
        if (examActive) e.preventDefault();
      }}
      onContextMenu={(e) => {
        if (examActive) e.preventDefault();
      }}
    >
      <div className="reading-progress" style={{ width: `${scroll * 100}%` }} />
      {!preview && (
        <aside className="sidebar">
          <button className="brand" onClick={() => { if (leave()) setPage("home"); }}>
            <BrandLogo/>
          </button>
          <h2>{outline?.code || outline?.title}</h2>
          <p className="course-subtitle">{outline?.code ? outline.title : outline?.term}</p>
          <button className="sidebar-courses" disabled={busy||examActive} onClick={()=>{if(leave())updateRoute({page:"courses",courseId:null});}}>All courses</button>
          <label className="lesson-picker">
            Lesson
            <select
              aria-label="Select lesson"
              value={lessonId || ""}
              disabled={busy}
              onChange={(e) => selectLesson(Number(e.target.value))}
            >
              <optgroup label="Course lessons">
                {outline?.lessons
                  .filter((l) => l.metadata?.kind !== "programming_quiz")
                  .map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.title}
                    </option>
                  ))}
              </optgroup>
              {outline?.lessons.some(
                (l) => l.metadata?.kind === "programming_quiz",
              ) && (
                <optgroup label="Programming quizzes">
                  {outline.lessons
                    .filter((l) => l.metadata?.kind === "programming_quiz")
                    .map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.title}
                      </option>
                    ))}
                </optgroup>
              )}
            </select>
          </label>
          <nav className="parts-navigation" aria-label="Assignment parts">
            {groups.map((group) => (
              <details
                key={group}
                open={
                  contentItems.find((a) => a.id === active)?.metadata.group ===
                    group || groups.length === 1
                }
              >
                <summary>{group.replace(/[-–—]+\s*$/, "").trim()}</summary>
                {contentItems
                  .filter((a) => (a.metadata.group || "Activities") === group)
                  .map((a) => (
                    <button
                      className={`lesson ${a.id === active ? "selected" : ""}`}
                      key={a.id}
                      onClick={() => navigate(a.id)}
                      disabled={busy}
                      title={
                        a.status === "completed"
                          ? "Completed"
                          : a.status === "viewed"
                            ? "Viewed; points not yet earned"
                            : "Not viewed"
                      }
                    >
                      {a.status === "completed" ? (
                        <CheckCircle2 className="status-complete" size={16} />
                      ) : a.status === "viewed" ? (
                        <CircleDot className="status-viewed" size={16} />
                      ) : (
                        <Circle size={16} />
                      )}
                      <span>{a.title}</span>
                      {a.metadata.kind === "coding" && <Code2 size={12} />}
                    </button>
                  ))}
              </details>
            ))}
            {!!psetItems.length && <button className={`sidebar-pset ${category==="problem_set"?"selected":""}`} disabled={busy} onClick={()=>selectCategory("problem_set")}><span className="pset-stack-icon"><Layers size={20}/></span><span><strong>Problem set</strong><small>{psetQuestions.filter(a=>Number(a.maximum_points)>0&&Number(a.earned_points)>=Number(a.maximum_points)).length} / {psetQuestions.length} completed</small></span><ChevronRight size={16}/></button>}
          </nav>
          <div className="navigation-legend">
            <span>
              <CheckCircle2 size={13} />
              Complete
            </span>
            <span>
              <CircleDot size={13} />
              In progress
            </span>
          </div>
        </aside>
      )}
      <main className="main">
        {!preview && (
          <header className="topbar">
            <button
              aria-label="Toggle navigation"
              onClick={() => setSidebar(!sidebar)}
            >
              <Layers size={19} />
            </button>
            <button onClick={() => { if (leave()) setPage("home"); }}>
              <House size={16} />
              Home
            </button>
            <div className="breadcrumbs">
              {lesson?.title}
              <ChevronRight size={13} />
              <strong>
                {category === "problem_set"
                  ? "Problem set"
                  : category === "supplemental"
                    ? "Resources"
                    : "Lesson content"}
              </strong>
            </div>

            <div className="topbar-actions">
              {canManage && (
                <button
                  className={outline?.student_view ? "student-view-active" : ""}
                  onClick={toggleStudentView}
                >
                  <Eye size={16} />
                  {outline?.student_view
                    ? "Exit student view"
                    : "Enter student view"}
                </button>
              )}
              {staff && (
                <button onClick={() => { if (leave()) setPage("settings"); }}>
                  <Users size={16} />
                  Course settings
                </button>
              )}

              <LogoutButton onConfirm={signOut}/>
            </div>
          </header>
        )}
        <>
          {!preview && (
            <div className="assignment-progress">
              <div>
                <span>
                  {lesson?.metadata?.kind === "programming_quiz"
                    ? "Programming quiz"
                    : category === "problem_set"
                      ? "Problem set"
                      : "Lesson"}{" "}
                  progress
                </span>
                <strong>
                  {maximumPoints > 0
                    ? `${earnedPoints} / ${maximumPoints} points`
                    : `${completed} / ${items.length} parts`}
                </strong>
              </div>
              <progress
                aria-label="Assignment progress"
                value={maximumPoints > 0 ? earnedPoints : completed}
                max={(maximumPoints > 0 ? maximumPoints : items.length) || 1}
              />
              {lesson?.metadata?.exam_mode && (
                <div
                  className={`quiz-timer ${quizSeconds === 0 ? "expired" : ""}`}
                >
                  <Clock3 size={17} />
                  <span>
                    {quizAttempt?.submitted
                      ? "Submitted"
                      : quizSeconds === null
                        ? "No time limit"
                        : quizSeconds === 0
                          ? "Time expired"
                          : formatCountdown(quizSeconds)}
                  </span>
                  {examActive && canManage && <button onClick={toggleStudentView}>Exit student view</button>}
                  {examActive && (
                    <button className="finish-quiz" disabled={busy} onClick={finishQuiz}>
                      Submit quiz
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
          {lesson?.metadata?.kind === "programming_quiz" && !preview && !config && !quizCompleted && items.length>0 &&
            (!examActive || !quizAttempt?.access_required) && <QuizNavigator questions={items} active={active} busy={busy}
              earned={earnedPoints} maximum={maximumPoints} onNavigate={navigate}/>}
          {lesson?.metadata?.exam_mode && !config && !preview && !staff && quizStatusLoaded && !quizCompleted &&
            (!quizAttempt?.attempt_id || quizAttempt.access_required) && <QuizAccessGate key={lesson.id}
              title={lesson.title} honorlock={!!quizAttempt?.honorlock_enabled} resuming={!!quizAttempt?.attempt_id}
              busy={busy} error={error} onBegin={beginQuiz}/>}
          {quizCompleted && (
            <section className="quiz-complete-screen">
              <CheckCircle2 size={42} />
              <span className="eyebrow">Programming quiz submitted</span>
              <h1>{lesson?.title}</h1>
              <p>Your quiz is closed.</p>
              {quizAttempt?.honorlock_enabled && <p role="status">{honorlockCompletion==="requesting"?"Notifying Honorlock that your quiz is submitted…":honorlockCompletion==="requested"?"A completion signal was sent to Honorlock. If recording continues, select Exit Honorlock to end your proctoring session.":"Select Exit Honorlock to finish your proctoring session."}</p>}
              <strong>
                {lesson?.metadata?.earned_points || "0"} /{" "}
                {lesson?.metadata?.maximum_points || "0"} points
              </strong>
              {canManage && <button className="primary" disabled={busy} onClick={resetQuizTest}><RotateCcw size={16}/>Reset my student-view attempt</button>}
            </section>
          )}
          {detail?.due_at && <div className="assignment-deadline">Due {new Date(detail.due_at).toLocaleString()}{detail.practice && <strong>Practice only · recorded scores are frozen</strong>}</div>}
          {(nativePractice || result?.practice) && <div className="notification">Practice attempt. Your recorded score has not changed.</div>}
          {!preview && !config && category==="problem_set" && !!psetQuestions.length && <ProblemSetNavigator parts={psetQuestions} active={active} busy={busy} onNavigate={navigate}/>}
          <div className="page-heading">
            <div>
              <h1>{detail?.title || "Loading…"}</h1>
            </div>
            <div className="heading-actions">
              {!preview && category!=="problem_set" && lesson?.metadata?.kind!=="programming_quiz" && <nav className="top-step-navigation" aria-label="Part navigation"><button aria-label="Previous part" disabled={chapterIndex<=0||busy} onClick={()=>void navigate(chapterSequence[chapterIndex-1].id)}><ArrowLeft size={17}/></button><span>{category==="problem_set" && psetQuestions.some(a=>a.id===active) ? `${psetQuestions.findIndex(a=>a.id===active)+1} / ${psetQuestions.length}` : `${index+1} / ${items.length}`}</span><button className="next-part" disabled={chapterIndex<0||chapterIndex>=chapterSequence.length-1||busy} onClick={()=>void navigate(chapterSequence[chapterIndex+1].id)}>{category!=="problem_set"&&chapterSequence[chapterIndex+1]?.metadata.category==="problem_set"?"Problem set":"Next"}<ArrowRight size={17}/></button></nav>}


              {preview ? (
                <button onClick={() => changeMode("config")}>
                  <X size={15} />
                  Close preview
                </button>
              ) : (
                staff && (
                  <div className="mode-switch">
                    <button
                      className={!config ? "on" : ""}
                      onClick={() => changeMode("student")}
                    >
                      {lesson?.metadata?.kind === "programming_quiz"
                        ? "Quiz"
                        : "Learn"}
                    </button>
                    <button
                      className={config ? "on" : ""}
                      onClick={() => changeMode("config")}
                    >
                      <Settings2 size={14} />
                      Config
                    </button>
                  </div>
                )
              )}
            </div>
          </div>
          {error && (
            <div className="notification error">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={15} />
              </button>
            </div>
          )}
          <PaceBanner lessonId={lessonId} signal={outline} enabled={!preview && !config && outline?.actual_role==="student" && !!lesson && lesson.metadata?.kind !== "programming_quiz"}/>
          {notice && (
            <div className="notification">
              {notice}
              <button
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          <div className="workspace-toolbar">
            <div className="activity-type">
              {coding ? <Code2 size={16} /> : <FileText size={16} />}
              <strong>
                {coding
                  ? sandbox
                    ? questions.length ? "Exercise + sandbox" : "Sandbox"
                    : "Coding exercise"
                  : questions.length
                    ? "Exercise"
                    : detail?.metadata.kind === "video"
                      ? "Video"
                      : "Reading"}
              </strong>
              {config && (
                <span>
                  Version {detail?.number} ·{" "}
                  {detail?.revision === detail?.published_revision
                    ? "Published"
                    : "Draft"}
                </span>
              )}
              {preview && <span>Preview</span>}
            </div>
            <div className="toolbar-actions">
              {!config &&
                !preview &&
                Number(detail?.maximum_points || 0) > 0 && (
                  <span
                    className={`exercise-score ${Number(result?.recorded_score ?? result?.score ?? detail?.earned_points ?? 0) >= Number(result?.maximum ?? detail?.maximum_points ?? 0) ? "full" : ""}`}
                  >
                    {result?.recorded_score ?? result?.score ?? detail?.earned_points ?? "0"} /{" "}
                    {result?.maximum ?? detail?.maximum_points ?? "0"} points
                  </span>
                )}
              {config && (
                <>
                  <button
                    disabled={dirty || busy || !detail}
                    onClick={() => changeMode("preview")}
                  >
                    <Eye size={15} />
                    Preview
                  </button>
                  <button
                    onClick={() =>
                      setEditorTab(
                        editorTab === "Content" ? "Files" : "Content",
                      )
                    }
                  >
                    Content
                  </button>
                  <button
                    onClick={() =>
                      setEditorTab(
                        editorTab === "Grading" ? "Files" : "Grading",
                      )
                    }
                  >
                    Grading
                  </button>
                  <button
                    onClick={() =>
                      setEditorTab(
                        editorTab === "History" ? "Files" : "History",
                      )
                    }
                  >
                    History
                  </button>
                </>
              )}
              {!config && coding && !placeholder && (
                <button
                  disabled={busy || loading}
                  onClick={() => setResetOpen(true)}
                >
                  <RotateCcw size={14} />
                  Reset workspace
                </button>
              )}
              {(config || (coding && !placeholder)) && (
                <>
                  <span className="save-state">
                    {dirty
                      ? "Unsaved changes"
                      : preview
                        ? "Temporary workspace"
                        : "Saved"}
                  </span>
                  <button disabled={!dirty || busy || loading} onClick={save}>
                    <Save size={14} />
                    Save
                  </button>
                </>
              )}
              {config && (
                <button
                  className="publish"
                  disabled={dirty || busy || !detail}
                  onClick={publish}
                >
                  Publish
                </button>
              )}
            </div>
          </div>
          {config && detail && editorTab !== "Files" && (
            <section className="config-panel">
              {editorTab === "Content" && (
                <>
                  <div className="builder-heading"><h2>Content blocks</h2><button aria-pressed={advancedContent} onClick={()=>setAdvancedContent(!advancedContent)}>{advancedContent?"Content builder":"Advanced JSON"}</button></div>
                  {!advancedContent ? <ContentBuilder content={contentDraft} grading={gradingDraft} disabled={busy||loading} onChange={(content,grading)=>{setContentDraft(content);setGradingDraft(grading);setDirty(true);}}/> : <div className="json-config-editor"><Suspense fallback={<div className="editor-loading">Opening editor…</div>}>
                    <EditorPane ariaLabel="Content blocks" path={`config/${active}/content.json`} value={contentDraft} theme={theme} disabled={busy||loading}
                      onChange={text=>{setContentDraft(text);setDirty(true);}} />
                  </Suspense></div>}
                </>
              )}
              {editorTab === "Grading" && (
                <>
                  <h2>Grading</h2>
                  <label>
                    Rubric points
                    <input
                      aria-label="Rubric points"
                      type="number"
                      min="0"
                      max="10000"
                      step="0.5"
                      value={points}
                      onChange={(e) => {
                        setPoints(e.target.value);
                        setDirty(true);
                      }}
                    />
                  </label>
                  <div className="json-config-label">Private grading configuration</div>
                  <div className="json-config-editor"><Suspense fallback={<div className="editor-loading">Opening editor…</div>}>
                    <EditorPane ariaLabel="Private grading configuration" path={`config/${active}/grading.json`} value={gradingDraft} theme={theme} disabled={busy||loading}
                      onChange={text=>{setGradingDraft(text);setDirty(true);}} />
                  </Suspense></div>
                </>
              )}
              {editorTab === "History" && (
                <>
                  <h2>Version history</h2>
                  {detail.history.map((h) => (
                    <p key={h.id}>
                      Version {h.number} ·{" "}
                      {new Date(h.created_at).toLocaleString()}
                    </p>
                  ))}
                </>
              )}
            </section>
          )}
          <div
            data-trellis-ed-version="1"
            data-allowed={!!detail && !loading && !config && !preview && !quizCompleted && lesson?.metadata?.kind !== "programming_quiz" && !!detail.ed_discussion_url && (coding || questions.length > 0) ? "true" : "false"}
            data-kind={lesson?.metadata?.kind || "lesson"}
            data-title={detail?.title || ""}
            data-assignment={lesson?.title || ""}
            data-activity={active || ""}
            data-lesson={lessonId || ""}
            data-ed-url={detail?.ed_discussion_url || ""}
            data-url={window.location.origin + window.location.pathname + routeHref({page:"course",lessonId,active,category,mode:"student"})}
            data-trellis-ed-workspace=""
            className={`activity-body ${coding && (!placeholder || config) ? "coding-layout" : "reading-layout"}${coding && questions.length ? " analysis-layout" : ""}`}
            style={
              { "--instructions-width": `${split}%` } as React.CSSProperties
            }
          >
            <section className="instructions" data-trellis-ed-instructions="">
              {detail?.content.blocks.map(renderBlock)}
              {questions.length > 0 && (
                <div className="native-submit">
                  <button
                    className="primary"
                    disabled={
                      busy ||
                      !detail?.grading_enabled ||
                      questions.every((q) => remainingSeconds(q.id) > 0)
                    }
                    onClick={submitNative}
                  >
                    {busy ? "Checking…" : "Submit answers"}
                  </button>
                  {((preview || config) ? questions.every(q=>solvedQuestions.has(q.id)) : (result?.reset_available ?? detail?.reset_available)) && (
                    <button disabled={busy || loading} onClick={resetNative}><RotateCcw size={16}/>Reset exercise</button>
                  )}
                  {!detail?.grading_enabled && (
                    <p>This exercise needs import review before grading.</p>
                  )}
                </div>
              )}
              {placeholder && (
                <div className="empty-state">
                  <Code2 size={24} />
                  <h3>Coding files pending import</h3>
                  <p>
                    This exercise will be available after its files and tests
                    are added.
                  </p>
                </div>
              )}
            </section>
            {coding && (!placeholder || config) && (
              <WorkspaceDivider value={split} onChange={setSplit} />
            )}
            {coding && (!placeholder || config) && (
              <section className="ide">
                <div className="runbar">
                  {!config && <span className="workspace-label"><Code2 size={16}/>Workspace</span>}
                  {config ? (
                    <span>Use Preview to run this exercise.</span>
                  ) : (
                    <div>
                      {detail?.revision === detail?.published_revision && lesson?.metadata?.kind !== "programming_quiz" && !sandbox && (detail?.visualization_available || (preview && executionResult?.passed)) && <button disabled={busy} onClick={()=>{if(leave())setPage("visualizer");}}><Braces size={16}/>Visualize sample</button>}
                      <button
                        disabled={
                          busy ||
                          !!quizAttempt?.submitted ||
                          !selected.endsWith(".py")
                        }
                        onClick={() => execute("run")}
                      >
                        <Play size={14} />
                        Run
                      </button>
                      {!sandbox && (
                        <button
                          className="primary"
                          disabled={
                            busy ||
                            !!quizAttempt?.submitted ||
                            !detail?.grading_enabled
                          }
                          onClick={() => execute("submit")}
                        >
                          Submit
                          <ArrowRight size={14} />
                        </button>
                      )}
                    </div>
                  )}
                </div>
                <div className="editor-main">
                  <div className="file-tree">
                    <div className="files-caption">
                      FILES
                      {config && (
                        <div>
                          <button
                            aria-label="New file"
                            onClick={() => {
                              setFilename("");
                              setFileDialog("new");
                            }}
                          >
                            <Plus size={14} />
                          </button>
                          <button
                            aria-label="Upload file"
                            onClick={() => input.current?.click()}
                          >
                            <Upload size={14} />
                          </button>
                        </div>
                      )}
                    </div>
                    {config && (
                      <input
                        type="file"
                        hidden
                        multiple
                        ref={input}
                        onChange={async (e) => {
                          const incoming = await Promise.all(
                            Array.from(e.target.files || []).map(async (f) => ({
                              path: f.name,
                              text: await f.text(),
                              visibility: fileAccess(f.name),
                            })),
                          );
                          if (
                            incoming.some((f) =>
                              files.some((old) => old.path === f.path),
                            )
                          ) {
                            setError("A file with this name already exists.");
                            return;
                          }
                          setFiles([...files, ...incoming]);
                          setDirty(true);
                        }}
                      />
                    )}
                    {files.map((f) => (
                      <button
                        className={`file ${selected === f.path ? "selected" : ""}`}
                        key={f.path}
                        onClick={() => setSelected(f.path)}
                      >
                        {f.visibility !== "student" ? (
                          <LockKeyhole size={13} />
                        ) : (
                          <FileCode2 size={13} />
                        )}
                        <span>{f.path}</span>
                      </button>
                    ))}
                    {config && current && (
                      <div className="file-actions">
                        <button
                          onClick={() => {
                            setFilename(selected);
                            setFileDialog("rename");
                          }}
                        >
                          <Pencil size={12} />
                          Rename
                        </button>
                        <button
                          onClick={() => {
                            setFiles(files.filter((f) => f.path !== selected));
                            setSelected(
                              files.find((f) => f.path !== selected)?.path ||
                                "",
                            );
                            setDirty(true);
                          }}
                        >
                          <Trash2 size={12} />
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="editor-pane">
                    <div className="file-tab">
                      <span>{selected}</span>
                      {!config && selected.split("/").pop() === "full_results.txt" && <small className="file-readonly"><LockKeyhole size={14}/>Read only</small>}
                    </div>
                    <Suspense
                      fallback={
                        <div className="editor-loading">Opening editor…</div>
                      }
                    >
                      <EditorPane
                        value={current?.text || ""}
                        height={questions.length ? "100%" : "450px"}
                        path={`${mode}/${detail?.revision}/${selected}`}
                        theme={theme}
                        disabled={!current || busy || (!config && selected.split("/").pop() === "full_results.txt")}
                        onChange={(text) => {
                          if (current && (config || selected.split("/").pop() !== "full_results.txt")) {
                            setFiles(
                              files.map((f) =>
                                f.path === selected ? { ...f, text } : f,
                              ),
                            );
                            setDirty(true);
                          }
                        }}
                      />
                    </Suspense>
                  </div>
                </div>
                <div className="console">
                  {executionResult?.passed && executionResult?.score !== undefined && (
                    <div className="grading-success">
                      <h3>{feedback.success_title}</h3>
                      <p>
                        {executionResult.practice ? "Practice complete. Your recorded score has not changed." : feedback.success_body}
                      </p>
                      {lesson?.metadata?.kind !== "programming_quiz" && (
                        <p>
                          If a sample answer is available, its file is now in
                          your workspace.
                        </p>
                      )}
                    </div>
                  )}
                  {lastOperation === "submit" &&
                    executionResult &&
                    !executionResult.passed &&
                    !executionResult.error && (
                      <div className="grading-failure">
                        <h3>{feedback.failure_title}</h3>
                        <p>
                          {feedback.failure_body}{" "}
                          <button
                            onClick={() => setSelected("full_results.txt")}
                          >
                            full_results.txt
                          </button>{" "}

                        </p>
                      </div>
                    )}
                  <div className="console-heading">
                    <Terminal size={14} />
                    <strong>Console</strong>
                  </div>
                  <pre className="live-console" aria-live="polite">
                    {busy
                      ? executionPhase
                      : executionResult?.error ||
                        (lastOperation === "run"
                          ? executionResult?.stdout
                          : executionResult?.preview) ||
                        (lastOperation === "run" &&
                        executionResult?.execution_status &&
                        executionResult.execution_status !== "ok"
                          ? executionResult.execution_status
                          : "") ||
                        "No output."}
                    {executionResult?.stale
                      ? "\nWorkspace changed; these results did not replace its files."
                      : ""}
                  </pre>
                </div>

              </section>
            )}
          </div>

        </>
      </main>
      {resetOpen && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="reset-title"
          >
            <h2 id="reset-title">Reset workspace?</h2>
            <p>
              Your edits and feedback will be replaced with the original files.
            </p>
            <button autoFocus onClick={() => setResetOpen(false)}>
              Cancel
            </button>
            <button className="primary" onClick={reset}>
              Restore original files
            </button>
          </section>
        </div>
      )}
      {fileDialog && (
        <div className="modal-backdrop">
          <form
            className="modal"
            onSubmit={(e) => {
              e.preventDefault();
              editFilename();
            }}
          >
            <h2>{fileDialog === "new" ? "New file" : "Rename file"}</h2>
            <label>
              Filename
              <input
                autoFocus
                value={filename}
                onChange={(e) => setFilename(e.target.value)}
              />
            </label>
            <button type="button" onClick={() => setFileDialog(null)}>
              Cancel
            </button>
            <button className="primary">Save</button>
          </form>
        </div>
      )}
    </div>
  );
}
