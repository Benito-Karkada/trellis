import { ArrowRight, BookOpen, ClipboardList, Settings2 } from "lucide-react";
import BrandLogo from "./BrandLogo";
import LogoutButton from "./LogoutButton";
import UnitOverview from "./UnitOverview";
import HomeNotebook from "./HomeNotebook";
import type { UpcomingItem } from "./UpcomingPanel";
import { routeHref } from "./navigation";
import "./homeRedesign.css";

type Part = { id: number; title: string; status: string; earned_points: string; maximum_points: string; metadata?: { kind?: string; category?: string } };
type Lesson = { id: number; title: string; metadata?: { kind?: string; unit_number?: number; earned_points?: string; maximum_points?: string; activity_count?: number; completed_count?: number }; activities: Part[] };
type Resume = { lesson_id: number; activity_id: number; lesson_title: string; activity_title: string; category: string };

/** The student view of the course home page (everything except the structure editor). */
export default function CourseHomeView({
  title, lessons, quizzes, canManage, resume, busy, error, notice,
  upcoming, onToggleUpcoming,
  onOpen, onGradebook, onSettings, onEditStructure, onSignOut,
}: {
  title: string;
  lessons: Lesson[];
  quizzes: Lesson[];
  canManage: boolean;
  resume?: Resume | null;
  busy: boolean;
  error: string;
  notice: string;
  upcoming?: UpcomingItem[];
  onToggleUpcoming?: (id: UpcomingItem["id"], done: boolean) => void;
  onOpen: (lesson: number, activity: number | null) => void;
  onGradebook: () => void;
  onSettings: () => void;
  onEditStructure: () => void;
  onSignOut: () => void;
}) {
  return (
    <div className="ch-shell">
      <header className="ch-nav">
        <div className="brand"><BrandLogo /></div>
        <div className="ch-nav-actions">
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
      {error && <div className="notification error" role="alert">{error}</div>}
      {notice && <div className="notification success" role="status">{notice}</div>}
      <div className="ch-body">
        <aside className="ch-panel">
          <div className="ch-hero">
            <span className="ch-hero-kicker">CS 1301</span>
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
          <HomeNotebook upcoming={upcoming} onToggleUpcoming={onToggleUpcoming} />
        </aside>
        <main className="ch-pages">
          <UnitOverview lessons={lessons} quizzes={quizzes} onOpen={onOpen} />
        </main>
      </div>
    </div>
  );
}
