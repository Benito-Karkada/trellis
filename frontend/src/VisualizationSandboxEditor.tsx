import { lazy, Suspense, useState } from "react";
import type { FormEvent } from "react";
import { Save, X } from "lucide-react";
import { api } from "./api";
const EditorPane = lazy(() => import("./EditorPane"));

export type CourseSandbox = {
  id: number;
  title: string;
  sandbox_name: string;
  description: string;
  source: string;
  version: number;
};

export default function VisualizationSandboxEditor({
  sandbox,
  initialSource,
  courseId,
  onSaved,
  onCancel,
}: {
  sandbox: CourseSandbox | null;
  initialSource: string;
  courseId: number | null;
  onSaved: (sandbox: CourseSandbox) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(sandbox?.title || "");
  const [name, setName] = useState(sandbox?.sandbox_name || "");
  const [description, setDescription] = useState(sandbox?.description || "");
  const [source, setSource] = useState(initialSource);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      const result = await api(
        `visualizations/library/${sandbox ? `${sandbox.id}/` : "new/"}`,
        {
          title,
          sandbox_name: name,
          description,
          source,
          ...(sandbox ? { version: sandbox.version } : {}),
        },
        courseId,
      );
      onSaved(result.sandbox);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <form
      className="viz-sandbox-editor"
      aria-label={
        sandbox ? "Edit visualization sandbox" : "New visualization sandbox"
      }
      onSubmit={save}
    >
      <header>
        <div>
          <span className="viz-eyebrow">Course library</span>
          <h2>{sandbox ? "Edit sandbox" : "New sandbox"}</h2>
        </div>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          aria-label="Close sandbox editor"
        >
          <X size={19} />
        </button>
      </header>
      <p>Saved sandboxes are available to everyone enrolled in this course.</p>
      <fieldset disabled={saving}>
        <div className="viz-sandbox-fields">
          <label>
            Title
            <input
              autoFocus
              required
              maxLength={160}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Nested loops"
            />
          </label>
          <label>
            Sandbox name
            <input
              required
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Multiplication table"
            />
          </label>
        </div>
        <label>
          Description <span>(optional)</span>
          <textarea
            rows={2}
            maxLength={1000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What should students explore?"
          />
        </label>
      </fieldset>
      <div className="viz-sandbox-code">
        <strong>Python code</strong>
        <Suspense fallback={<p>Opening editor…</p>}>
          <EditorPane
            path={`visualizer-authoring/${courseId}/${sandbox?.id || "new"}.py`}
            value={source}
            onChange={setSource}
            disabled={saving}
            theme="light"
            height="300px"
            ariaLabel="Sandbox Python code"
          />
        </Suspense>
      </div>
      {error && (
        <div className="viz-alert error" role="alert">
          {error}
        </div>
      )}
      <footer>
        <button
          className="primary"
          disabled={saving || !title.trim() || !name.trim() || !source.trim()}
        >
          <Save size={16} />
          {saving ? "Saving…" : sandbox ? "Save changes" : "Create sandbox"}
        </button>
        <button type="button" disabled={saving} onClick={onCancel}>
          Cancel
        </button>
      </footer>
    </form>
  );
}
