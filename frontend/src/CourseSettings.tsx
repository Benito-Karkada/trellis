import BrandLogo from "./BrandLogo";
import {HonorlockSettings} from "./Honorlock";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  Clock3,
  Cloud,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Upload,
  UserCog,
  Users,
  KeyRound,
  Copy,
  X,
} from "lucide-react";
import { api, upload } from "./api";
import CourseControls from "./CourseControls";
import CanvasPublishing from "./CanvasPublishing";
import CourseIdentity from "./CourseIdentity";
import {EdDiscussionSettings} from "./EdDiscussion";
import ApiAccess from "./ApiAccess";
import SubmissionReview from "./SubmissionReview";
import DiscussionSelect from "./DiscussionSelect";

type Member = {
  id: number;
  email: string;
  name: string;
  role: string;
  active: boolean;
  source: string;
  account_ready: boolean;
};
type Student = Member & {
  time_percent: string;
  extra_minutes: number;
  extra_attempts: number;
  effective_minutes: string | null;
};
type Activity = {
  id: number | string;
  title: string;
  lesson: string;
  time_limit_minutes: number | null;
};
type Quiz = {
  id: number;
  title: string;
  visibility: string;
  exam_mode: boolean;
  honorlock_enabled?: boolean;
  honorlock_password_set?: boolean;
  time_limit_minutes: number | null;
  question_count: number;
};

const roleLabel = (role: string) =>
  ({
    student: "Student",
    ta: "Teaching assistant",
    head_ta: "TA",
    instructor: "Instructor",
  })[role] || role;

export default function CourseSettings({
  course,
  onBack,
  theme,
}: {
  course: string;
  onBack: () => void;
  theme: "light" | "dark";
}) {
  const [tab, setTab] = useState<"course" | "canvas" | "enrollment" | "accommodations" | "quizzes" | "grading" | "api" | "review" | "integrations">(
      "enrollment",
    ),
    [members, setMembers] = useState<Member[]>([]),
    [students, setStudents] = useState<Student[]>([]),
    [activities, setActivities] = useState<Activity[]>([]),
    [quizzes, setQuizzes] = useState<Quiz[]>([]);
  const [email, setEmail] = useState(""),
    [name, setName] = useState(""),
    [role, setRole] = useState("student"),
    [csvRole, setCsvRole] = useState("student"),
    [activity, setActivity] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set()),
    [percent, setPercent] = useState("150"),
    [extraMinutes, setExtraMinutes] = useState("0"),
    [extraAttempts, setExtraAttempts] = useState("0");
  const [rowValues, setRowValues] = useState<
      Record<number, { percent: string; minutes: string; attempts: string }>
    >({}),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [error, setError] = useState("");
  const [studentSearch, setStudentSearch] = useState("");
  const studentSearchInput = useRef<HTMLInputElement>(null);
  const matchingStudents = useMemo(() => {
    const terms = studentSearch.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return students.filter(student => terms.every(term =>
      `${student.name} ${student.email}`.toLocaleLowerCase().includes(term)));
  }, [students, studentSearch]);
  const studentById = new Map(students.map(student => [student.id, student]));
  const selectedStudents = [...selected].map(id => studentById.get(id)).filter((student): student is Student => !!student);
  const suggestions = matchingStudents.filter(student => !selected.has(student.id));
  const allMatchingSelected = matchingStudents.length > 0 && matchingStudents.every(student => selected.has(student.id));
  function selectStudent(id: number, checked: boolean) {
    setSelected(previous => {
      const next = new Set(previous);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }
  function addStudent(id: number) {
    selectStudent(id, true);
    setStudentSearch("");
    studentSearchInput.current?.focus();
  }
  const file = useRef<HTMLInputElement>(null);
  const [canManageLogins,setCanManageLogins]=useState(false);
  const [currentMemberId,setCurrentMemberId]=useState<number|null>(null);
  const [loginMember,setLoginMember]=useState<Member|null>(null);
  const [createLogin,setCreateLogin]=useState(true);
  const [loginPassword,setLoginPassword]=useState("");
  const [createdLogin,setCreatedLogin]=useState<{email:string;password:string}|null>(null);
  async function loadRoster() {
    const data = await api("settings/roster/");
    setMembers(data.members);
    setCanManageLogins(data.can_manage_logins === true);
    setCurrentMemberId(data.current_member_id);
  }
  async function removeMember(member:Member) {
    if (!window.confirm(`Remove ${member.name || member.email} from this course? Their work and grades will be preserved. Re-enrolling the same email restores access.`)) return;
    await act(async()=>{await api(`settings/enrollments/${member.id}/remove/`,{}); await loadRoster();setNotice("Enrollment removed.");});
  }
  async function loadAccommodations(value = activity) {
    const data = await api(
      `settings/accommodations/${value ? `?activity=${value}` : ""}`,
    );
    setStudents(data.students);
    const validIds = new Set<number>(data.students.map((student: Student) => student.id));
    setSelected(previous => new Set([...previous].filter(id => validIds.has(id))));
    setActivities(data.activities);
    setRowValues(
      Object.fromEntries(
        data.students.map((s: Student) => [
          s.id,
          {
            percent: s.time_percent,
            minutes: String(s.extra_minutes),
            attempts: String(s.extra_attempts),
          },
        ]),
      ),
    );
  }
  async function loadQuizzes() {
    const data = await api("settings/quizzes/");
    setQuizzes(data.quizzes);
  }
  useEffect(() => {
    setNotice("");setError("");
    if(tab==="course" || tab==="canvas" || tab==="review" || tab==="api" || tab==="grading" || tab==="integrations")return;
    const loading=tab==="enrollment" ? loadRoster() : tab==="accommodations" ? loadAccommodations(activity) : loadQuizzes();
    loading.catch((e) => setError(e.message));
  }, [tab]);
  const teachers = useMemo(
      () => members.filter((m) => m.active && m.role !== "student"),
      [members],
    ),
    learners = useMemo(
      () => members.filter((m) => m.active && m.role === "student"),
      [members],
    );
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function add(e: React.FormEvent) {
    e.preventDefault();
    await act(async () => {
      const data = await api("settings/enrollments/", { email, name, role });
      if(canManageLogins && createLogin && !data.member.account_ready){
        setCreatedLogin(await api(`settings/enrollments/${data.member.id}/login/`,{password:loginPassword || undefined}));
      }
      setNotice(
        data.created
          ? `${data.member.email} was added.`
          : `${data.member.email} was updated.`,
      );
      setEmail("");
      setName("");
      setLoginPassword("");
      await loadRoster();
    });
  }
  async function importCsv(files: FileList | null) {
    const chosen = files?.[0];
    if (!chosen) return;
    await act(async () => {
      const body = new FormData();
      body.append("file", chosen);
      body.append("role", csvRole);
      const data = await upload("settings/enrollments/import/", body);
      setNotice(
        `${data.added} added · ${data.updated} updated${data.errors.length ? ` · ${data.errors.length} rows need attention` : ""}`,
      );
      await loadRoster();
    });
    if (file.current) file.current.value = "";
  }
  async function sync() {
    await act(async () => {
      const data = await api("settings/roster/sync/", {});
      setNotice(
        `Canvas synced: ${data.added} added, ${data.updated} updated, ${data.deactivated} deactivated${data.skipped ? `, ${data.skipped} skipped` : ""}.`,
      );
      await loadRoster();
    });
  }
  async function chooseActivity(value: string) {
    setActivity(value);
    setStudentSearch("");
    setSelected(new Set());
    await act(() => loadAccommodations(value));
  }
  function provision(member:Member){
    setCreatedLogin(null);
    setLoginMember(member);
  }
  async function saveLogin(password:string){
    if (!loginMember) return;
    const data=await api(`settings/enrollments/${loginMember.id}/login/`,{
      reset:loginMember.account_ready,password:password || undefined,
    });
    setCreatedLogin(data);
    setLoginMember(null);
    loadRoster().catch(e=>setError(e.message));
  }
  async function saveBatch(
    ids: number[],
    values = { percent, minutes: extraMinutes, attempts: extraAttempts },
  ) {
    await act(async () => {
      const data = await api("settings/accommodations/save/", {
        membership_ids: ids,
        activity_id: activity || null,
        time_percent: values.percent,
        extra_minutes: values.minutes,
        extra_attempts: values.attempts,
      });
      setNotice(
        `${data.updated} accommodation${data.updated === 1 ? "" : "s"} saved.`,
      );
      await loadAccommodations(activity);
    });
  }
  async function saveQuiz(quiz: Quiz, changes: Partial<Quiz>) {
    await act(async () => {
      const changedLimit = Object.prototype.hasOwnProperty.call(
        changes,
        "time_limit_minutes",
      )
        ? changes.time_limit_minutes
        : quiz.time_limit_minutes;
      await api(`settings/quizzes/${quiz.id}/`, {
        time_limit_minutes: changedLimit ?? "",
        exam_mode: changes.exam_mode ?? quiz.exam_mode,
        visibility: changes.visibility ?? quiz.visibility,
      });
      setNotice(
        `${quiz.title} settings saved${
          (changes.visibility ?? quiz.visibility) === "student"
            ? " — visible to students."
            : " — hidden from students."
        }`,
      );
      await loadQuizzes();
      await loadAccommodations(activity);
    });
  }
  async function resetQuizTest(quiz:Quiz){
    if(!window.confirm(`Reset your own test attempt for ${quiz.title}, including your work and score? Student attempts will not change.`))return;
    await act(async()=>{
      await api(`quizzes/${quiz.id}/reset-test/`,{});
      setNotice(`Your test attempt for ${quiz.title} was reset. Student attempts were not changed.`);
    });
  }
  return (
    <div className="settings-shell">
      <header className="settings-header">
        <button className="settings-back" onClick={onBack}>
          <ArrowLeft size={18} />
          Back to home
        </button>
        <a className="brand" href="/">
          <BrandLogo/>
        </a>

      </header>
      <main className="settings-main">
        <div className="settings-heading">
          <span className="auth-kicker">{course}</span>
          <h1>Course settings</h1>
          <p>Instructors manage enrollment, accommodations, integrations, and course policies. TAs can edit course content and review student work.</p>
        </div>
        <nav className="settings-tabs"><button className={tab==="course"?"active":""} onClick={()=>setTab("course")}>Course details</button><button className={tab==="canvas"?"active":""} onClick={()=>setTab("canvas")}>Publish to Canvas</button>
          <button
            className={tab === "enrollment" ? "active" : ""}
            onClick={() => setTab("enrollment")}
          >
            <Users size={18} />
            Enrollment
          </button>
          <button
            className={tab === "accommodations" ? "active" : ""}
            onClick={() => setTab("accommodations")}
          >
            <Clock3 size={18} />
            Accommodations
          </button>
          <button
            className={tab === "quizzes" ? "active" : ""}
            onClick={() => setTab("quizzes")}
          >
            <ShieldCheck size={18} />
            Programming quizzes
          </button>
          <button className={tab === "integrations" ? "active" : ""} onClick={()=>setTab("integrations")}>Integrations</button>
          <button className={tab === "grading" ? "active" : ""} onClick={()=>setTab("grading")}>Assignments & grading</button>
          <button className={tab === "review" ? "active" : ""} onClick={()=>setTab("review")}>Submission review</button>
          <button className={tab === "api" ? "active" : ""} onClick={()=>setTab("api")}><KeyRound size={17}/>API access</button>
        </nav>
        {error && <div className="notification error">{error}</div>}
        {notice && <div className="notification">{notice}</div>}
        {loginMember && <LoginPasswordDialog member={loginMember} onSave={saveLogin} onClose={()=>setLoginMember(null)}/>}
        {createdLogin && <section className="login-created" role="status"><div><KeyRound size={21}/><strong>Login ready</strong><button aria-label="Dismiss login details" onClick={()=>setCreatedLogin(null)}><X size={18}/></button></div><p>Share these details with this person. No email has been sent.</p><dl><dt>Email</dt><dd>{createdLogin.email}</dd><dt>Password</dt><dd><code>{createdLogin.password}</code></dd></dl><button onClick={()=>navigator.clipboard.writeText(`Trellis\n${window.location.origin}/\nEmail: ${createdLogin.email}\nPassword: ${createdLogin.password}`)}><Copy size={16}/> Copy login details</button></section>}
        {tab === "course" ? <CourseIdentity/> : tab === "canvas" ? <CanvasPublishing/> : tab === "integrations" ? <EdDiscussionSettings/> : tab === "review" ? <SubmissionReview theme={theme}/> : tab === "api" ? <ApiAccess/> : tab === "grading" ? <CourseControls/> : tab === "enrollment" ? (
          <div className="settings-grid">
            {canManageLogins && <section className="settings-card enrollment-tools">
              <div className="card-title">
                <div>
                  <h2>Add people</h2>
                  <p>Add one person or upload a class list.</p>
                </div>
                <UserCog />
              </div>
              <form onSubmit={add}>
                {canManageLogins && <div className="login-options"><label className="login-checkbox"><input type="checkbox" checked={createLogin} onChange={e=>setCreateLogin(e.target.checked)}/>Create a login when adding a new account</label>{createLogin && <label>Password <span>leave blank to generate one</span><input type="password" autoComplete="new-password" value={loginPassword} onChange={e=>setLoginPassword(e.target.value)} minLength={8}/></label>}</div>}
                <div className="form-row">
                  <label>
                    Email address
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="student@gatech.edu"
                      required
                    />
                  </label>
                  <label>
                    Name <span>optional</span>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="First and last name"
                    />
                  </label>
                </div>
                <label>
                  Course role
                  <DiscussionSelect label="Course role" value={role} onChange={setRole}
                    options={[{value:"student",label:"Student"},{value:"instructor",label:"Instructor"},{value:"ta",label:"TA"}]} />
                </label>
                <button className="primary" disabled={busy}>
                  <Plus size={16} />
                  Add person
                </button>
              </form>
              <div className="settings-rule" />
              <div className="csv-control">
                <div>
                  <strong>Upload a CSV</strong>
                  <p>Use an email column; a name column is optional.</p>
                </div>
                <DiscussionSelect label="Role for CSV import" value={csvRole} onChange={setCsvRole}
                  options={[{value:"student",label:"Students"},{value:"instructor",label:"Instructors"},{value:"ta",label:"TAs"}]} />
                <input
                  ref={file}
                  hidden
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => importCsv(e.target.files)}
                />
                <button disabled={busy} onClick={() => file.current?.click()}>
                  <Upload size={16} />
                  Choose CSV
                </button>
              </div>
              <div className="settings-rule" />
              <button className="canvas-sync" disabled={busy} onClick={sync}>
                <Cloud size={18} />
                <span>
                  <strong>Sync roster with Canvas</strong>
                  <small>
                    Pull current enrollments through the connected LTI course.
                  </small>
                </span>
                <RefreshCw size={16} />
              </button>
            </section>
            }
            <section className="settings-card roster-card">
              <div className="card-title">
                <div>
                  <h2>Course roster</h2>
                  <p>
                    {learners.length} students · {teachers.length} staff
                  </p>
                </div>
              </div>
              <h3>Teaching team</h3>
              <div className="member-list">
                {teachers.map((m) => (
                  <MemberRow key={m.id} member={m} onProvision={canManageLogins ? ()=>provision(m) : undefined} onRemove={canManageLogins && m.id!==currentMemberId ? ()=>removeMember(m) : undefined} busy={busy}/>
                ))}
              </div>
              <h3>Students</h3>
              <div className="member-list">
                {learners.map((m) => (
                  <MemberRow key={m.id} member={m} onProvision={canManageLogins ? ()=>provision(m) : undefined} onRemove={canManageLogins && m.id!==currentMemberId ? ()=>removeMember(m) : undefined} busy={busy}/>
                ))}
              </div>
            </section>
          </div>
        ) : tab === "accommodations" ? (
          <div className="accommodation-layout">
            <section className="settings-card accommodation-scope">
              <div className="card-title">
                <div>
                  <h2>Accommodation scope</h2>
                  <p>
                    Apply accommodations coursewide or to one programming quiz.
                  </p>
                </div>
                <Clock3 />
              </div>
              <label>
                Programming quiz
                <DiscussionSelect label="Programming quiz" value={activity} onChange={chooseActivity}
                  options={[{value:"",label:"Coursewide default"},...activities.map(quiz => ({value:String(quiz.id),label:quiz.title}))]} />
              </label>
            </section>
            <section className="settings-card batch-card">
              <div className="card-title">
                <div>
                  <h2>Batch accommodation</h2>
                  <p>Apply one adjustment to every selected student.</p>
                </div>
                <Users />
              </div>
              <div className="accommodation-recipients">
                <div className="accommodation-selection-heading">
                  <label htmlFor="accommodation-student-search">Students</label>
                  {selected.size > 0 && <button type="button" className="recipient-clear" disabled={busy}
                    onClick={() => setSelected(new Set())}>Clear selection</button>}
                </div>
                <div className="recipient-picker">
                  {selectedStudents.length > 0 && <ul className="recipient-pills" aria-label="Selected students">
                    {selectedStudents.map(student => <li key={student.id} className="recipient-pill" title={student.email}>
                      <span>{student.name || student.email}</span>
                      <button type="button" disabled={busy} aria-label={`Remove ${student.name || student.email} from selection`}
                        onClick={() => selectStudent(student.id, false)}><X size={14}/></button>
                    </li>)}
                  </ul>}
                  <div className="recipient-search">
                    <Search size={18} aria-hidden="true"/>
                    <input id="accommodation-student-search" ref={studentSearchInput} type="search"
                      placeholder="Search by name or email" value={studentSearch} disabled={busy}
                      autoComplete="off" aria-describedby="accommodation-selection-summary"
                      onChange={event => setStudentSearch(event.target.value)}
                      onKeyDown={event => {
                        if (event.key === "Enter" && studentSearch.trim() && suggestions.length === 1) {
                          event.preventDefault();addStudent(suggestions[0].id);
                        }
                      }}/>
                    {studentSearch && <button type="button" aria-label="Clear student search" disabled={busy}
                      onClick={() => {setStudentSearch("");studentSearchInput.current?.focus();}}><X size={16}/></button>}
                  </div>
                </div>
                {studentSearch.trim() && <div className="recipient-results" aria-label="Matching students">
                  {suggestions.slice(0, 20).map(student => <button type="button" className="recipient-result"
                    key={student.id} disabled={busy} onClick={() => addStudent(student.id)}
                    aria-label={`Add ${student.name || student.email} to selection`}>
                    <span><strong>{student.name || student.email}</strong>{student.name && <small>{student.email}</small>}</span>
                    <Plus size={18} aria-hidden="true"/>
                  </button>)}
                  {suggestions.length === 0 && <p>{matchingStudents.length ? "All matching students are selected." : "No students match this search."}</p>}
                  {suggestions.length > 20 && <p>Showing 20 of {suggestions.length} matches. Keep typing to narrow your search.</p>}
                </div>}
                <p id="accommodation-selection-summary" className="recipient-summary" role="status">
                  {selected.size ? `${selected.size} student${selected.size === 1 ? "" : "s"} selected` : "Search to add students, or select them in the roster below."}
                </p>
              </div>
              <div className="batch-fields">
                <label>
                  Time allowed
                  <input
                    type="number"
                    min="100"
                    max="1000"
                    value={percent}
                    onChange={(e) => setPercent(e.target.value)}
                  />
                  <span>%</span>
                </label>
                <label>
                  Extra minutes
                  <input
                    type="number"
                    min="0"
                    value={extraMinutes}
                    onChange={(e) => setExtraMinutes(e.target.value)}
                  />
                </label>
                <label>
                  Extra attempts
                  <input
                    type="number"
                    min="0"
                    value={extraAttempts}
                    onChange={(e) => setExtraAttempts(e.target.value)}
                  />
                </label>
                <button
                  className="primary"
                  disabled={busy || !selected.size}
                  onClick={() => saveBatch([...selected])}
                >
                  Apply to {selected.size || "selected"}
                </button>
              </div>
            </section>
            <section className="settings-card student-accommodations">
              <div className="card-title">
                <div>
                  <h2>Student accommodations</h2>
                  <p>
                    Set a different percentage or extra time for an individual
                    student.
                  </p>
                </div>
              </div>
              <p className="accommodation-roster-count">{studentSearch.trim() ? `${matchingStudents.length} matching student${matchingStudents.length === 1 ? "" : "s"}` : `${students.length} students`}</p>
              <div className="accommodation-table">
                <div className="accommodation-head">
                  <input
                    type="checkbox"
                    aria-label={studentSearch.trim() ? "Select all matching students" : "Select all students"}
                    checked={allMatchingSelected}
                    disabled={busy || matchingStudents.length === 0}
                    ref={element => {if (element) element.indeterminate = !allMatchingSelected && matchingStudents.some(student => selected.has(student.id));}}
                    onChange={event => {
                      const checked = event.target.checked;
                      setSelected(previous => {
                        const next = new Set(previous);
                        matchingStudents.forEach(student => checked ? next.add(student.id) : next.delete(student.id));
                        return next;
                      });
                    }}
                  />
                  <span>Student</span>
                  <span>Time</span>
                  <span>Extra minutes</span>
                  <span>Extra attempts</span>
                  <span>Effective time</span>
                  <span />
                </div>
                {matchingStudents.length === 0 && <p className="accommodation-empty">{students.length ? "No students match this search." : "No students are enrolled yet."}</p>}
                {matchingStudents.map((student) => {
                  const value = rowValues[student.id] || {
                    percent: "100",
                    minutes: "0",
                    attempts: "0",
                  };
                  return (
                    <div className="accommodation-row" key={student.id}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${student.email}`}
                        checked={selected.has(student.id)}
                        disabled={busy}
                        onChange={event => selectStudent(student.id, event.target.checked)}
                      />
                      <span className="member-primary">
                        <strong>{student.name || student.email}</strong>
                        <small>{student.name && student.email}</small>
                      </span>
                      <label>
                        <input
                          aria-label={`Time percent for ${student.email}`}
                          type="number"
                          min="100"
                          max="1000"
                          value={value.percent}
                          onChange={(e) =>
                            setRowValues({
                              ...rowValues,
                              [student.id]: {
                                ...value,
                                percent: e.target.value,
                              },
                            })
                          }
                        />
                        <span>%</span>
                      </label>
                      <input
                        aria-label={`Extra minutes for ${student.email}`}
                        type="number"
                        min="0"
                        value={value.minutes}
                        onChange={(e) =>
                          setRowValues({
                            ...rowValues,
                            [student.id]: { ...value, minutes: e.target.value },
                          })
                        }
                      />
                      <input
                        aria-label={`Extra attempts for ${student.email}`}
                        type="number"
                        min="0"
                        value={value.attempts}
                        onChange={(e) =>
                          setRowValues({
                            ...rowValues,
                            [student.id]: {
                              ...value,
                              attempts: e.target.value,
                            },
                          })
                        }
                      />
                      <span>
                        {student.effective_minutes
                          ? `${student.effective_minutes} min`
                          : activity
                            ? "Set quiz time"
                            : "Course default"}
                      </span>
                      <button
                        disabled={busy}
                        onClick={() => saveBatch([student.id], value)}
                      >
                        <Check size={15} />
                        Save
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>
          </div>
        ) : (
          <QuizSettings quizzes={quizzes} busy={busy} onSave={saveQuiz} onReset={resetQuizTest} onQuizzesChanged={loadQuizzes}/>
        )}
      </main>
    </div>
  );
}

function QuizSettings({
  quizzes,
  busy,
  onSave,
  onReset,
  onQuizzesChanged,
}: {
  quizzes: Quiz[];
  busy: boolean;
  onSave: (quiz: Quiz, changes: Partial<Quiz>) => Promise<void>;
  onReset: (quiz:Quiz)=>Promise<void>;
  onQuizzesChanged:()=>Promise<void>;
}) {
  const [minutes, setMinutes] = useState<Record<number, string>>({});
  return (
    <section className="quiz-settings settings-card">
      <div className="card-title">
        <div>
          <h2>Programming quizzes</h2>
          <p>Set exam mode and the time available for each quiz.</p>
        </div>
        <ShieldCheck />
      </div>
      <div className="quiz-list">
        {quizzes.map((quiz) => (
          <article className="quiz-setting" key={quiz.id}>
            <div>
              <span className="quiz-number">
                {quiz.question_count} questions
              </span>
              <h3>{quiz.title}</h3>
              <button disabled={busy} onClick={()=>onReset(quiz)}>Reset my test attempt</button>
            </div>
            <label className="exam-switch publish-switch">
              <input
                type="checkbox"
                checked={quiz.visibility === "student"}
                onChange={(e) =>
                  onSave(quiz, {
                    visibility: e.target.checked ? "student" : "staff",
                  })
                }
              />
              <span>
                {quiz.visibility === "student"
                  ? "Published to students"
                  : "Hidden from students"}
              </span>
            </label>
            <label className="exam-switch">
              <input
                type="checkbox"
                checked={quiz.exam_mode}
                onChange={(e) => onSave(quiz, { exam_mode: e.target.checked })}
              />
              <span>Exam mode</span>
            </label>
            <label>
              Time limit
              <div className="timing-input">
                <input
                  type="number"
                  min="1"
                  max="1440"
                  placeholder="No limit"
                  value={minutes[quiz.id] ?? quiz.time_limit_minutes ?? ""}
                  onChange={(e) =>
                    setMinutes({ ...minutes, [quiz.id]: e.target.value })
                  }
                />
                <span>minutes</span>
              </div>
            </label>
            <button
              disabled={busy}
              onClick={() =>
                onSave(quiz, {
                  time_limit_minutes:
                    Number(minutes[quiz.id] ?? quiz.time_limit_minutes) || null,
                })
              }
            >
              <Check size={16} />
              Save settings
            </button>
            <HonorlockSettings key={`${quiz.id}-${quiz.honorlock_enabled}-${quiz.honorlock_password_set}`} quiz={quiz} onSaved={onQuizzesChanged} busy={busy}/>
          </article>
        ))}
      </div>
    </section>
  );
}

function MemberRow({ member,onProvision,onRemove,busy }: { member: Member;onProvision?:()=>void;onRemove?:()=>void;busy?:boolean }) {
  return (
    <div className="member-row">
      <span className="member-avatar">
        {(member.name || member.email).slice(0, 2).toUpperCase()}
      </span>
      <span className="member-primary">
        <strong>{member.name || member.email}</strong>
        <small>{member.name && member.email}</small>
      </span>
      <span className="role-pill">{roleLabel(member.role)}</span>
      <span className={`source-pill ${member.source}`}>
        {member.source === "canvas" ? "Canvas" : "Manual"}
      </span>
      {!member.account_ready && (
        <span className="invite-state">Account pending</span>
      )}
      {onRemove && <button className="member-remove" disabled={busy} onClick={onRemove} aria-label={`Remove ${member.email}`}>Remove</button>}
      {onProvision && <button className="member-login" disabled={busy} onClick={onProvision}><KeyRound size={15}/>{member.account_ready ? "Reset password" : "Create login"}</button>}
    </div>
  );
}

function LoginPasswordDialog({member,onSave,onClose}:{member:Member;onSave:(password:string)=>Promise<void>;onClose:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null);
  const [password,setPassword]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
  useEffect(()=>{const element=dialog.current;element?.showModal();return()=>element?.close();},[]);
  async function submit(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError("");
    try{await onSave(password);}catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  return <dialog ref={dialog} className="login-password-dialog" aria-labelledby="login-password-title" onCancel={event=>{event.preventDefault();if(!busy)onClose();}}>
    <form onSubmit={submit}>
      <div className="login-password-heading"><KeyRound size={23}/><h2 id="login-password-title">{member.account_ready?"Reset password":"Create login"}</h2><button type="button" aria-label="Close password dialog" disabled={busy} onClick={onClose}><X size={20}/></button></div>
      <p className="login-password-email">{member.email}</p>
      {member.account_ready&&<p>The current password will stop working when you save.</p>}
      <label htmlFor="account-new-password">New password</label>
      <input id="account-new-password" type="password" autoComplete="new-password" autoFocus minLength={8} value={password} onChange={event=>setPassword(event.target.value)} disabled={busy} aria-describedby="account-password-help"/>
      <p id="account-password-help">Choose a password with at least 8 characters, or leave blank to generate one.</p>
      {error&&<div className="notification error" role="alert">{error}</div>}
      <div className="login-password-actions"><button type="button" disabled={busy} onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy?"Saving…":password?"Save password":"Generate password"}</button></div>
    </form>
  </dialog>;
}
