import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  BookOpen,
  GraduationCap,
  Plus,
  Search,
  X,
} from "lucide-react";
import BrandLogo from "./BrandLogo";
import LogoutButton from "./LogoutButton";
import { api } from "./api";
import { routeHref } from "./navigation";
import "./courses.css";

type Course = {
  id: number;
  title: string;
  code: string;
  term: string;
  description: string;
  role: string;
  section_count: number;
  example: boolean;
};
export default function CourseLibrary({
  onOpen,
  onSignOut,
}: {
  onOpen: (id: number) => void;
  onSignOut: () => void;
}) {
  const [data, setData] = useState<{
    courses: Course[];
    can_create: boolean;
  } | null>(null);
  const [search, setSearch] = useState(""),
    [error, setError] = useState(""),
    [creating, setCreating] = useState(false),
    [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    title: "",
    code: "",
    term: "",
    description: "",
  });
  useEffect(() => {
    let current = true;
    api("courses/")
      .then((value) => {
        if (current) setData(value);
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, []);
  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const course = await api("courses/", form);
      onOpen(course.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const courses =
    data?.courses.filter((course) =>
      `${course.title} ${course.code} ${course.term}`
        .toLowerCase()
        .includes(search.toLowerCase()),
    ) || [];
  return (
    <div className="course-library ch-shell">
      <header className="ch-nav">
        <BrandLogo />
        <LogoutButton onConfirm={onSignOut} />
      </header>
      <main className="library-main">
        <section className="library-heading">
          <div>
            <span className="ch-kicker">YOUR WORKSPACE</span>
            <h1>Courses</h1>
            <p>
              Lessons, practice, and progress. Each course has its own space.
            </p>
          </div>
          {data?.can_create && (
            <button
              className="primary"
              onClick={() => {
                setCreating(true);
                setError("");
              }}
            >
              <Plus size={18} />
              Create a course
            </button>
          )}
        </section>
        {!creating && error && (
          <div className="notification error" role="alert">
            {error}
          </div>
        )}
        <label className="library-search">
          <Search size={18} />
          <input
            aria-label="Find a course"
            placeholder="Find a course by title, code, or term"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        {!data && !error && <p role="status">Loading your courses…</p>}
        {data && (
          <div className="library-grid">
            {courses.map((course) => (
              <a
                className="library-card"
                href={routeHref({ page: "home", courseId: course.id })}
                key={course.id}
                onClick={(e) => {
                  if (!e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) {
                    e.preventDefault();
                    onOpen(course.id);
                  }
                }}
              >
                <div className="library-card-top">
                  <span className="library-course-icon">
                    <BookOpen size={25} />
                  </span>
                  <span className="library-role">
                    {course.role === "instructor"
                      ? "Instructor"
                      : course.role === "student"
                        ? "Student"
                        : "Teaching assistant"}
                  </span>
                </div>
                <span className="ch-kicker">
                  {[course.code, course.term].filter(Boolean).join(" · ") ||
                    `COURSE ${course.id}`}
                </span>
                <h2>{course.title}</h2>
                <p>
                  {course.description ||
                    (course.example
                      ? "Explore the CS 1301 proof of concept."
                      : "Your course content and assignments.")}
                </p>
                <footer>
                  <span>
                    {course.section_count} section
                    {course.section_count === 1 ? "" : "s"}
                    {course.example && <small>Proof of concept</small>}
                  </span>
                  <ArrowUpRight size={22} />
                </footer>
              </a>
            ))}
          </div>
        )}
        {data && !courses.length && (
          <section className="library-empty">
            <GraduationCap size={36} />
            <h2>{search ? "No matching courses" : "No courses yet"}</h2>
            <p>
              {search
                ? "Try a different title, code, or term."
                : data.can_create
                  ? "Create your first course, then add sections and activities."
                  : "Your instructor can enroll you using your account email."}
            </p>
          </section>
        )}
      </main>
      {creating && (
        <div className="modal-backdrop">
          <section
            className="course-create-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-course-title"
          >
            <header>
              <div>
                <span className="ch-kicker">START SOMETHING NEW</span>
                <h2 id="create-course-title">Create a course</h2>
              </div>
              <button
                disabled={busy}
                aria-label="Close create course"
                onClick={() => setCreating(false)}
              >
                <X size={20} />
              </button>
            </header>
            <p>
              Start with a blank course. Build content here and publish
              assignments to Canvas when you’re ready.
            </p>
            <form onSubmit={create}>
              <label>
                Course title
                <input
                  autoFocus
                  required
                  maxLength={200}
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Introduction to Environmental Science"
                />
              </label>
              <div className="form-row">
                <label>
                  Course code
                  <input
                    maxLength={40}
                    value={form.code}
                    onChange={(e) => setForm({ ...form, code: e.target.value })}
                    placeholder="EAS 1600"
                  />
                </label>
                <label>
                  Term
                  <input
                    maxLength={40}
                    value={form.term}
                    onChange={(e) => setForm({ ...form, term: e.target.value })}
                    placeholder="Spring 2027"
                  />
                </label>
              </div>
              <label>
                Description
                <textarea
                  rows={3}
                  maxLength={1000}
                  value={form.description}
                  onChange={(e) =>
                    setForm({ ...form, description: e.target.value })
                  }
                  placeholder="What will students learn?"
                />
              </label>
              {error && (
                <div className="notification error" role="alert">
                  {error}
                </div>
              )}
              <div className="dialog-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setCreating(false)}
                >
                  Cancel
                </button>
                <button className="primary" disabled={busy}>
                  {busy ? "Creating…" : "Create course"}
                  <ArrowUpRight size={17} />
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
