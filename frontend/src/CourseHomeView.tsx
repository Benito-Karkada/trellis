import { ArrowRight, BookOpen, Braces, ClipboardList, Settings2 } from "lucide-react";
import BrandLogo from "./BrandLogo";
import LogoutButton from "./LogoutButton";
import UnitOverview from "./UnitOverview";
import HomeNotebook from "./HomeNotebook";
import type { useUpcoming } from "./useUpcoming";
import { routeHref } from "./navigation";
import "./homeRedesign.css";
import "./visualization.css";

type Part = { id: number; title: string; status: string; earned_points: string; maximum_points: string; metadata?: { kind?: string; category?: string } };
type Lesson = { id: number; title: string; metadata?: { kind?: string; unit_number?: number; earned_points?: string; maximum_points?: string; activity_count?: number; completed_count?: number }; activities: Part[] };
type Resume = { lesson_id: number; activity_id: number; lesson_title: string; activity_title: string; category: string };

/** The student view of the course home page (everything except the structure editor). */
export default function CourseHomeView({
  title, code, term, example, onCourses, lessons, quizzes, canManage, resume, busy, error, notice,
  upcoming,
  onVisualize, onOpen, onGradebook, onSettings, onDiscussions, onEditStructure, onSignOut,
}: {
  title: string;
  example: boolean;
  code: string;
  term: string;
  onCourses: () => void;
  lessons: Lesson[];
  quizzes: Lesson[];
  canManage: boolean;
  resume?: Resume | null;
  busy: boolean;
  error: string;
  notice: string;
  upcoming: ReturnType<typeof useUpcoming>;
  onVisualize: () => void;
  onOpen: (lesson: number, activity: number | null) => void;
  onGradebook: () => void;
  onSettings: () => void;
  onDiscussions: () => void;
  onEditStructure: () => void;
  onSignOut: () => void;
}) {
  return (
    <div className="ch-shell">
      <header className="ch-nav">
        <div className="brand"><BrandLogo /></div>
        <div className="ch-nav-actions"><button className="ch-nav-link" onClick={onCourses}><BookOpen size={17}/>All courses</button>
          {canManage && (
            <>
              <button className="ch-nav-link" onClick={onGradebook}><ClipboardList size={17} />Gradebook</button>
              <button className="ch-nav-link" onClick={onSettings}><Settings2 size={17} />Course settings</button>
              <button className="ch-nav-link" disabled={busy} onClick={onEditStructure}><BookOpen size={17} />Edit course structure</button>
            </>
          )}
          <LogoutButton onConfirm={onSignOut} />
        </div>
      </header>
      <nav className="ch-course-tabs" aria-label="Course tools"><span aria-current="page"><BookOpen size={17}/>Course</span><button onClick={onVisualize}><Braces size={18}/>Code visualizer</button></nav>
      {error && <div className="notification error" role="alert">{error}</div>}
      {notice && <div className="notification success" role="status">{notice}</div>}
      <div className="ch-body">
        <aside className="ch-panel">
          <div className="ch-hero">
            <span className="ch-hero-kicker">{[code,term].filter(Boolean).join(" · ") || "YOUR COURSE"}</span>
            <h1>{title}</h1>
            <p>Lessons, problem sets, and programming assessments.</p>
          </div>
          {resume && (
            <a className="ch-resume"
              href={routeHref({ page: "course", lessonId: resume.lesson_id, active: resume.activity_id, category: resume.category })}
              onClick={(event) => {
                if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                onOpen(resume.lesson_id, resume.activity_id);
              }}>
              <BookOpen className="ch-resume-icon" size={44} strokeWidth={1.6} aria-hidden="true" />
              <div className="ch-resume-text">
                <small>Pick up where you left off</small>
                <strong>{resume.activity_title}</strong>
                <span>{resume.lesson_title}</span>
              </div>
              <span className="ch-resume-continue">Continue <ArrowRight size={18} /></span>
            </a>
          )}
          <HomeNotebook upcoming={upcoming} onOpen={onOpen} onManageDeadlines={canManage ? onSettings : undefined} />
        </aside>
        <main className="ch-pages">
          {!lessons.length&&!quizzes.length&&<section className="library-empty"><BookOpen size={34}/><h2>Your course starts here</h2><p>{canManage?"Add your first section, then build lessons, videos, questions, and coding exercises.":"Your instructor is preparing this course. Check back for new content."}</p>{canManage&&<button className="primary" onClick={onEditStructure}>Add course content</button>}</section>}
          <UnitOverview lessons={lessons} quizzes={quizzes} onOpen={onOpen} onDiscussions={onDiscussions} />
        </main>
      </div>
    </div>
  );
}
