import { useEffect, useState } from "react";
import { api } from "./api";
type Identity = {
  title: string;
  code: string;
  term: string;
  description: string;
  can_edit: boolean;
};
export default function CourseIdentity() {
  const [data, setData] = useState<Identity | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  useEffect(() => {
    api("settings/course/")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!data) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("settings/course/", {
        title: data.title,
        code: data.code,
        term: data.term,
        description: data.description,
      });
      setNotice("Course details saved.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!data) return <p role="status">{error || "Loading course details…"}</p>;
  return (
    <section className="settings-card">
      <h2>Course details</h2>
      <p>This information appears in the course library and course home.</p>
      <form className="course-identity-form" onSubmit={save}>
        <label>
          Course title
          <input
            required
            maxLength={200}
            value={data.title}
            readOnly={!data.can_edit}
            onChange={(e) => setData({ ...data, title: e.target.value })}
          />
        </label>
        <div className="form-row">
          <label>
            Course code
            <input
              maxLength={40}
              value={data.code}
              readOnly={!data.can_edit}
              onChange={(e) => setData({ ...data, code: e.target.value })}
            />
          </label>
          <label>
            Term
            <input
              maxLength={40}
              value={data.term}
              readOnly={!data.can_edit}
              onChange={(e) => setData({ ...data, term: e.target.value })}
            />
          </label>
        </div>
        <label>
          Description
          <textarea
            rows={3}
            maxLength={1000}
            value={data.description}
            readOnly={!data.can_edit}
            onChange={(e) => setData({ ...data, description: e.target.value })}
          />
        </label>
        {error && <p role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {data.can_edit && (
          <button className="primary" disabled={busy}>
            {busy ? "Saving…" : "Save course details"}
          </button>
        )}
      </form>
    </section>
  );
}
