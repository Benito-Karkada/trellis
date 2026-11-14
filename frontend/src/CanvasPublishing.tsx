import { useEffect, useRef, useState } from "react";
import { Check, ExternalLink, RefreshCw, Send } from "lucide-react";
import { api } from "./api";
type Assignment = {
  id: number;
  title: string;
  points: string;
  due_at: string | null;
  url: string;
  part_count: number;
  visibility: string;
  canvas_assignment_id: string;
  status: string;
  last_error: string;
  synced_at: string | null;
  published: boolean;
};
type Data = {
  course_id: number;
  canvas_course_id: string;
  trellis_url: string;
  configured: boolean;
  can_publish: boolean;
  assignments: Assignment[];
};
export default function CanvasPublishing() {
  const mounted = useRef(true);
  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );
  const [data, setData] = useState<Data | null>(null),
    [target, setTarget] = useState(""),
    [site, setSite] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set()),
    [visible, setVisible] = useState(false),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState("");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [filter, setFilter] = useState(""),
    [mapping, setMapping] = useState<Assignment | null>(null),
    [mapId, setMapId] = useState("");
  async function load(initial = false) {
    const value: Data = await api("settings/canvas/assignments/");
    setData(value);
    if (initial) {
      setTarget(value.canvas_course_id);
      setSite(value.trellis_url || window.location.origin);
    }
  }
  useEffect(() => {
    load(true).catch((e) => setError(e.message));
  }, []);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("settings/canvas/configure/", {
        canvas_course_id: target,
        trellis_url: site,
      });
      await load();
      setNotice("Canvas course settings saved.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    if (!data) return;
    const rows = data.assignments.filter(
      (a) => selected.has(a.id) && a.part_count,
    );
    setBusy(true);
    setError("");
    setNotice("");
    let completed = 0;
    const failures: string[] = [];
    for (const [index, row] of rows.entries()) {
      if (!mounted.current) break;
      setProgress(`${index + 1} of ${rows.length} · ${row.title}`);
      try {
        await api(
          `settings/canvas/assignments/${row.id}/publish/`,
          { published: visible },
          data.course_id,
        );
        completed++;
      } catch (e) {
        failures.push(`${row.title}: ${(e as Error).message}`);
      }
    }
    if (!mounted.current) return;
    await load().catch((e) => failures.push(e.message));
    setProgress("");
    setBusy(false);
    setNotice(
      `${completed} assignment${completed === 1 ? "" : "s"} ${visible ? "published" : "saved as drafts"} in Canvas.`,
    );
    setError(failures.join("\n"));
    setSelected(new Set());
  }
  async function link(event: React.FormEvent) {
    event.preventDefault();
    if (!mapping) return;
    setBusy(true);
    setError("");
    try {
      await api("settings/course-controls/save/", {
        assignment_id: mapping.id,
        due_at: mapping.due_at,
        canvas_assignment_id: mapId,
      });
      setMapping(null);
      await load();
      setNotice(
        "Existing Canvas assignment linked. Future publishes update this assignment.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!data)
    return <p role="status">{error || "Loading Canvas publishing…"}</p>;
  const rows = data.assignments.filter((a) =>
    a.title.toLowerCase().includes(filter.toLowerCase()),
  );
  const eligible = rows.filter((a) => a.part_count > 0);
  const connectionDirty =
    target !== data.canvas_course_id ||
    site.replace(/\/$/, "") !== data.trellis_url;
  const ready =
    data.configured &&
    !!data.canvas_course_id &&
    !!data.trellis_url &&
    !connectionDirty;
  const preview = data.assignments.filter((a) => selected.has(a.id));
  return (
    <div className="canvas-publishing">
      {error && (
        <div
          className="notification error"
          role="alert"
          style={{ whiteSpace: "pre-line" }}
        >
          {error}
        </div>
      )}
      {notice && (
        <div className="notification success" role="status">
          {notice}
        </div>
      )}
      <section className="settings-card">
        <span className="ch-kicker">AUTHOR HERE. CONNECT THERE.</span>
        <h2>Canvas publishing</h2>
        <p>
          Create your course in Trellis, then send assignments to Canvas. Each
          section becomes one Canvas assignment, with the total points from its
          published graded parts. Students do their work in Trellis.
        </p>
        {!data.configured && (
          <div className="canvas-setup-note">
            Preview is available. To publish, set <code>CANVAS_BASE_URL</code>{" "}
            and <code>CANVAS_API_TOKEN</code> on the backend. Credentials stay
            on the server.
          </div>
        )}
        <form className="canvas-config-form" onSubmit={save}>
          <label>
            Canvas course ID
            <input
              value={target}
              pattern="[0-9]+"
              required
              readOnly={!data.can_publish}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="12345"
            />
          </label>
          <label>
            Trellis site URL
            <input
              type="url"
              required
              value={site}
              readOnly={!data.can_publish}
              onChange={(e) => setSite(e.target.value)}
              placeholder="https://trellis.example.edu"
            />
          </label>
          {data.can_publish && <button disabled={busy}>Save connection</button>}
        </form>
        {(site.includes("localhost") || site.includes("127.0.0.1")) && (
          <p className="canvas-local-note">
            Local preview: this link opens on your computer. Use a hosted
            Trellis URL when sharing assignments with students.
          </p>
        )}
      </section>
      <section className="settings-card">
        <div className="canvas-list-heading">
          <div>
            <h2>Choose assignments</h2>
            <p>
              Titles, published point totals and due dates come from Trellis.
              Edit content in the course; edit deadlines in Assignments &
              grading.
            </p>
          </div>
          <button
            disabled={busy}
            onClick={() => load().catch((e) => setError(e.message))}
          >
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>
        <input
          className="canvas-search"
          aria-label="Find an assignment to publish"
          placeholder="Find an assignment"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="canvas-table-wrap">
          <table className="canvas-assignment-table">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label="Select all visible assignments"
                    disabled={busy || !eligible.length || !data.can_publish}
                    checked={
                      !!eligible.length &&
                      eligible.every((a) => selected.has(a.id))
                    }
                    onChange={(e) =>
                      setSelected((old) => {
                        const next = new Set(old);
                        eligible.forEach((a) =>
                          e.target.checked ? next.add(a.id) : next.delete(a.id),
                        );
                        return next;
                      })
                    }
                  />
                </th>
                <th>Assignment</th>
                <th>Points</th>
                <th>Due date</th>
                <th>Canvas</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select ${a.title}`}
                      disabled={busy || !a.part_count || !data.can_publish}
                      checked={selected.has(a.id)}
                      onChange={(e) =>
                        setSelected((old) => {
                          const next = new Set(old);
                          if (e.target.checked) next.add(a.id);
                          else next.delete(a.id);
                          return next;
                        })
                      }
                    />
                  </td>
                  <td>
                    <strong>{a.title}</strong>
                    <small>
                      {a.part_count} published parts
                      {a.visibility === "staff"
                        ? " · Staff-only in Trellis"
                        : ""}
                    </small>
                    {a.url && (
                      <a href={a.url} target="_blank" rel="noreferrer">
                        Preview Trellis link <ExternalLink size={12} />
                      </a>
                    )}
                  </td>
                  <td>{a.points}</td>
                  <td>
                    {a.due_at
                      ? new Date(a.due_at).toLocaleString()
                      : "No due date"}
                  </td>
                  <td>
                    <span
                      className={`canvas-status ${a.status === "synced" ? "synced" : ""}`}
                    >
                      {a.status === "synced" ? (
                        <>
                          <Check size={14} />
                          {a.published ? "Published" : "Draft"}
                        </>
                      ) : a.status === "not_published" ? (
                        "Not linked"
                      ) : a.status === "linked" ? (
                        "Linked"
                      ) : a.status === "uncertain" ? (
                        "Check Canvas"
                      ) : a.status === "publishing" ? (
                        "In progress"
                      ) : a.status === "failed" ? (
                        "Needs attention"
                      ) : (
                        a.status
                      )}
                    </span>
                    {a.last_error && <small>{a.last_error}</small>}
                    {data.can_publish && (
                      <button
                        className="canvas-link-existing"
                        disabled={busy}
                        onClick={() => {
                          setMapping(a);
                          setMapId(a.canvas_assignment_id);
                        }}
                      >
                        {a.canvas_assignment_id
                          ? `Assignment ${a.canvas_assignment_id}`
                          : "Link an existing assignment"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows.length && (
          <p>
            No assignments yet. Add a section and publish its content to get
            started.
          </p>
        )}
      </section>
      {!!preview.length && (
        <section className="settings-card canvas-publish-preview">
          <h2>Ready to send</h2>
          <p>
            {preview.length} selected ·{" "}
            {preview.filter((a) => !a.canvas_assignment_id).length} new ·{" "}
            {preview.filter((a) => a.canvas_assignment_id).length} updates.
            Existing mappings are updated in place. Quiz questions and solutions
            stay in Trellis.
          </p>
          <label className="canvas-publish-check">
            <input
              type="checkbox"
              checked={visible}
              disabled={busy}
              onChange={(e) => setVisible(e.target.checked)}
            />
            Publish in Canvas so students can see these assignments
          </label>
          <p>
            {visible
              ? "Students can see these assignments in Canvas immediately. Trellis visibility rules still apply."
              : "Assignments will be saved as unpublished drafts in Canvas."}
          </p>
          <button
            className="primary"
            disabled={busy || !ready || !data.can_publish}
            onClick={publish}
          >
            <Send size={16} />
            {busy
              ? "Sending…"
              : visible
                ? "Publish selected to Canvas"
                : "Create / update Canvas drafts"}
          </button>
          {progress && <p role="status">{progress}</p>}
          {!ready && (
            <p>
              {connectionDirty
                ? "Save the connection settings above before publishing."
                : "Complete the connection settings above to enable publishing."}
            </p>
          )}
        </section>
      )}
      {mapping && (
        <div className="modal-backdrop">
          <section
            className="course-create-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="link-canvas-title"
          >
            <h2 id="link-canvas-title">Link a Canvas assignment</h2>
            <p>{mapping.title}</p>
            <p>
              Use the assignment ID from its Canvas URL in this course. This
              also recovers a create request whose response was interrupted.
            </p>
            <form onSubmit={link}>
              <label>
                Canvas assignment ID
                <input
                  autoFocus
                  required
                  pattern="[0-9]+"
                  value={mapId}
                  onChange={(e) => setMapId(e.target.value)}
                />
              </label>
              {error && <p role="alert">{error}</p>}
              <div className="dialog-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setMapping(null)}
                >
                  Cancel
                </button>
                <button className="primary" disabled={busy}>
                  Link assignment
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
