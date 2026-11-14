import { useEffect, useState } from "react";
import { api } from "./api";
type Assignment = {
  id: number;
  title: string;
  due_at: string | null;
};
type Controls = {
  assignments: Assignment[];
  feedback: Record<string, string>;
};
const localDate = (value: string | null) => {
  if (!value) return "";
  const d = new Date(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
};
export default function CourseControls() {
  const [data, setData] = useState<Controls | null>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  async function load() {
    setData(await api("settings/course-controls/"));
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);
  async function save(body: unknown) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("settings/course-controls/save/", body);
      setNotice("Saved.");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!data)
    return <p role="status">{error || "Loading assignment settings…"}</p>;
  return (
    <div className="course-controls">
      {error && (
        <div role="alert" className="notification error">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="notification">
          {notice}
        </div>
      )}
      <section className="settings-card">
        <h2>Assignment deadlines</h2>
        <p>
          Times use your browser’s local time zone. After the deadline, feedback
          and practice remain available; recorded scores stay unchanged.
          Individual deadline accommodations take precedence. Changing a date
          applies to future attempts and does not regrade past practice.
        </p>
        <div className="deadline-table">
          {data.assignments.map((a) => (
            <AssignmentDeadline
              key={`${a.id}/${a.due_at}`}
              assignment={a}
              busy={busy}
              onSave={save}
            />
          ))}
        </div>
      </section>
      <section className="settings-card">
        <h2>Grading feedback</h2>
        <p>
          These messages apply across the course. Quiz feedback never offers
          students sample answers.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save({ feedback: data.feedback });
          }}
          className="feedback-settings"
        >
          {Object.entries(data.feedback).map(([key, text]) => (
            <label key={key}>
              {
                (
                  {
                    success_title: "Success heading",
                    success_body: "Success message",
                    failure_title: "Try-again heading",
                    failure_body: "Try-again message",
                  } as Record<string, string>
                )[key]
              }
              <textarea
                required
                maxLength={2000}
                value={text}
                onChange={(e) =>
                  setData({
                    ...data,
                    feedback: { ...data.feedback, [key]: e.target.value },
                  })
                }
              />
            </label>
          ))}
          <button className="primary" disabled={busy}>
            Save course feedback
          </button>
        </form>
      </section>
    </div>
  );
}
function AssignmentDeadline({
  assignment: a,
  busy,
  onSave,
}: {
  assignment: Assignment;
  busy: boolean;
  onSave: (body: unknown) => Promise<void>;
}) {
  const [due, setDue] = useState(localDate(a.due_at));
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave({
          assignment_id: a.id,
          due_at: due ? new Date(due).toISOString() : null,
        });
      }}
    >
      <strong>{a.title}</strong>
      <label>
        Due date
        <input
          type="datetime-local"
          value={due}
          onChange={(e) => setDue(e.target.value)}
        />
      </label>
      <button disabled={busy}>Save</button>
    </form>
  );
}
