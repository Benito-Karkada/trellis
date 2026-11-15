import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Braces,
  ChevronLeft,
  ChevronRight,
  Code2,
  Layers,
  Pause,
  Plus,
  Play,
  RotateCcw,
  SquarePen,
} from "lucide-react";
import BrandLogo from "./BrandLogo";
import { api } from "./api";
import VisualizationSandboxEditor from "./VisualizationSandboxEditor";
import type { CourseSandbox } from "./VisualizationSandboxEditor";
import { readRoute } from "./navigation";
import { visualizationExamples } from "./visualizationExamples";
import "./visualization.css";
const EditorPane = lazy(() => import("./EditorPane"));
type Value = {
  type?: string;
  value?: string | number | boolean | null;
  ref?: string;
  truncated?: boolean;
};
type HeapItem = {
  type: string;
  items: [string | Value, Value][];
  truncated?: boolean;
};
type Frame = { name: string; line: number; locals: Record<string, Value> };
type Step = {
  line: number;
  event: string;
  frames: Frame[];
  heap: Record<string, HeapItem>;
  stdout: string;
  returned?: Value;
  exception?: string;
};
type Trace = {
  steps: Step[];
  truncated: boolean;
  status: string;
  stdout: string;
};
type Samples = {
  title: string;
  revision: number;
  selected_case: string;
  cases: { id: string; label: string; stdin: string }[];
  samples: { path: string; source: string }[];
};
export default function CodeVisualizer({
  activity,
  onBack,
}: {
  activity?: number | null;
  onBack: () => void;
}) {
  const courseId = readRoute().courseId;
  const [sandboxes, setSandboxes] = useState<CourseSandbox[]>([]);
  const [canEditLibrary, setCanEditLibrary] = useState(false);
  const [libraryError, setLibraryError] = useState("");
  const [libraryRetry, setLibraryRetry] = useState(0);
  const [authoring, setAuthoring] = useState<"new" | "edit" | null>(null);
  const [savedNotice, setSavedNotice] = useState("");
  const [exampleId, setExampleId] = useState("for");
  const customSandbox = sandboxes.find(
    (row) => `course-${row.id}` === exampleId,
  );
  const allExamples = [
    ...visualizationExamples,
    ...sandboxes.map((row) => ({
      id: `course-${row.id}`,
      title: row.title,
      topic: "Course sandboxes",
      description:
        row.description || "Edit this program and step through its execution.",
      focus: row.sandbox_name,
      source: row.source,
    })),
  ];
  const example =
    allExamples.find((row) => row.id === exampleId) || visualizationExamples[0];
  const [source, setSource] = useState(example.source);
  const [samples, setSamples] = useState<Samples | null>(null),
    [samplePath, setSamplePath] = useState("");
  const [loading, setLoading] = useState(!!activity),
    [busy, setBusy] = useState(false),
    [phase, setPhase] = useState("");
  const [error, setError] = useState(""),
    [trace, setTrace] = useState<Trace | null>(null),
    [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false),
    [delay, setDelay] = useState(900),
    [focused, setFocused] = useState("");
  const sequence = useRef(0),
    timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    setSandboxes([]);
    setCanEditLibrary(false);
    setLibraryError("");
    setAuthoring(null);
    if (activity) return;
    let current = true;
    api("visualizations/library/", undefined, courseId)
      .then((data) => {
        if (current) {
          setSandboxes(data.sandboxes);
          setCanEditLibrary(data.can_edit);
        }
      })
      .catch((failure) => {
        if (current) setLibraryError(failure.message);
      });
    return () => {
      current = false;
    };
  }, [activity, courseId, libraryRetry]);
  const step = trace?.steps[index],
    previous = trace?.steps[index - 1];
  const final = !!trace && index === trace.steps.length - 1;
  useEffect(() => {
    const version = ++sequence.current;
    setTrace(null);
    setPlaying(false);
    setBusy(false);
    setError("");
    setSamples(null);
    setSamplePath("");

    if (!activity) {
      setSource(visualizationExamples[0].source);
      setExampleId("for");
      setLoading(false);
      return;
    }
    setLoading(true);
    api(`visualizations/samples/${activity}/`)
      .then((data: Samples) => {
        if (version !== sequence.current) return;
        setSamples(data);
        setSamplePath(data.samples[0].path);
        setSource(data.samples[0].source);
      })
      .catch((e) => {
        if (version === sequence.current) setError(e.message);
      })
      .finally(() => {
        if (version === sequence.current) setLoading(false);
      });
    return () => {
      sequence.current++;
      clearTimeout(timer.current);
    };
  }, [activity, courseId]);
  useEffect(() => {
    if (!playing || !trace) return;
    if (index >= trace.steps.length - 1) {
      setPlaying(false);
      return;
    }
    const tick = setTimeout(() => setIndex((old) => old + 1), delay);
    return () => clearTimeout(tick);
  }, [playing, index, delay, trace]);
  useEffect(
    () => () => {
      sequence.current++;
      clearTimeout(timer.current);
    },
    [],
  );
  async function selectInput(caseId: string) {
    clearTrace();
    setLoading(true);
    const version = ++sequence.current;
    try {
      const data: Samples = await api(
        `visualizations/samples/${activity}/?case=${encodeURIComponent(caseId)}`,
      );
      if (version !== sequence.current) return;
      setSamples(data);
      setSource(
        (data.samples.find((row) => row.path === samplePath) || data.samples[0])
          .source,
      );
    } catch (e) {
      if (version === sequence.current) setError((e as Error).message);
    } finally {
      if (version === sequence.current) setLoading(false);
    }
  }
  function clearTrace() {
    setTrace(null);
    setPlaying(false);
    setIndex(0);
    setFocused("");
    setError("");
  }
  async function buildTrace() {
    if (busy || loading || authoring) return;
    clearTrace();
    setBusy(true);
    setPhase("Queued for the Python runner…");
    const version = ++sequence.current;
    const deadline = Date.now() + 310000;
    try {
      const job = await api(
        "visualizations/",
        activity
          ? {
              activity,
              sample: samplePath,
              revision: samples?.revision,
              case: samples?.selected_case,
              stdin:
                samples?.cases.find((row) => row.id === samples.selected_case)
                  ?.stdin || "",
            }
          : { source },
      );
      const poll = async () => {
        if (version !== sequence.current) return;
        try {
          const state = await api(`visualizations/${job.id}/`);
          if (version !== sequence.current) return;
          if (state.status === "completed" || state.status === "failed") {
            if (state.result.error) throw Error(state.result.error);
            if (!state.result.trace)
              throw Error(
                "No trace was returned. Check that the worker supports visualization.",
              );
            setTrace(state.result.trace);
            setIndex(0);
            setBusy(false);
            return;
          }
          if (Date.now() > deadline)
            throw Error(
              "The runner did not respond. Start the local execution worker and try again.",
            );
          setPhase(
            state.status === "running"
              ? "Tracing Python execution…"
              : "Queued for the Python runner…",
          );
          timer.current = setTimeout(() => void poll(), 700);
        } catch (e) {
          if (version === sequence.current) {
            setError((e as Error).message);
            setBusy(false);
          }
        }
      };
      await poll();
    } catch (e) {
      if (version === sequence.current) {
        setError((e as Error).message);
        setBusy(false);
      }
    }
  }
  function value(value: Value, heap: Record<string, HeapItem> = {}) {
    if (value.ref)
      return (
        <button
          className={`viz-reference ${focused === value.ref ? "selected" : ""}`}
          title={`View ${heap[value.ref]?.type || "object"} #${value.ref}`}
          onClick={() => setFocused(value.ref!)}
        >
          ↗ {heap[value.ref]?.type || "object"} #{value.ref}
        </button>
      );
    const text =
      value.type === "str"
        ? JSON.stringify(value.value)
        : value.value === null
          ? "None"
          : typeof value.value === "boolean"
            ? value.value
              ? "True"
              : "False"
            : String(value.value);
    return (
      <span className={`viz-value type-${value.type}`}>
        <code>
          {text}
          {value.truncated ? "…" : ""}
        </code>
        <small>{value.type}</small>
      </span>
    );
  }
  const done =
    final &&
    step?.event === "return" &&
    step.frames.length === 1 &&
    trace?.status === "ok" &&
    !trace.truncated;
  const topics = [...new Set(allExamples.map((row) => row.topic))];
  return (
    <div className="viz-shell">
      <header className="viz-nav">
        <button className="brand" onClick={onBack}>
          <BrandLogo />
        </button>
        <div className="viz-nav-tabs">
          <button onClick={onBack}>
            <BookOpen size={17} />
            {activity ? "Back to exercise" : "Course"}
          </button>
          <span aria-current="page">
            <Braces size={18} />
            Code visualizer
          </span>
        </div>
      </header>
      <main className="viz-main">
        <div className="viz-heading">
          <div>
            <span className="viz-eyebrow">
              {activity ? "Unlocked walkthrough" : "Python lab"}
            </span>
            <h1>
              {activity
                ? samples?.title || "Sample answer walkthrough"
                : "Code visualizer"}
            </h1>
            <p>
              {activity
                ? "Step through a sample answer. Your workspace and score stay as they are."
                : "Choose an example or edit the code, then step through its execution."}
            </p>
          </div>
          {!activity && canEditLibrary && (
            <button
              className="viz-add-sandbox"
              disabled={busy || !!authoring}
              onClick={() => {
                setSavedNotice("");
                setAuthoring("new");
              }}
            >
              <Plus size={17} /> Add sandbox
            </button>
          )}
        </div>
        {!activity && libraryError && (
          <div className="viz-alert error" role="alert">
            Course sandboxes couldn’t load: {libraryError}{" "}
            <button onClick={() => setLibraryRetry((value) => value + 1)}>
              Try again
            </button>
          </div>
        )}
        {savedNotice && (
          <div className="viz-sandbox-notice" role="status">
            {savedNotice}
          </div>
        )}
        {authoring && canEditLibrary && (
          <VisualizationSandboxEditor
            key={`${authoring}-${customSandbox?.id || "new"}`}
            sandbox={authoring === "edit" ? customSandbox || null : null}
            initialSource={
              authoring === "edit" ? source : 'print("Hello, Trellis!")\n'
            }
            courseId={courseId}
            onCancel={() => setAuthoring(null)}
            onSaved={(row) => {
              setSandboxes((current) =>
                [...current.filter((item) => item.id !== row.id), row].sort(
                  (a, b) => a.title.localeCompare(b.title),
                ),
              );
              setExampleId(`course-${row.id}`);
              setSource(row.source);
              clearTrace();
              setAuthoring(null);
              setSavedNotice("Sandbox saved to the course library.");
            }}
          />
        )}
        {!activity && (
          <div className="viz-library" aria-label="Python examples">
            {topics.map((topic) => (
              <section key={topic}>
                <h2>{topic}</h2>
                {allExamples
                  .filter((row) => row.topic === topic)
                  .map((row) => (
                    <button
                      key={row.id}
                      aria-pressed={row.id === exampleId}
                      disabled={busy || !!authoring}
                      onClick={() => {
                        clearTrace();
                        setSavedNotice("");
                        setExampleId(row.id);
                        setSource(row.source);
                      }}
                    >
                      <span>
                        {row.title}
                        {row.id.startsWith("course-") && (
                          <small className="viz-library-name">
                            {
                              sandboxes.find(
                                (item) => `course-${item.id}` === row.id,
                              )?.sandbox_name
                            }
                          </small>
                        )}
                      </span>
                      <ArrowRight size={15} />
                    </button>
                  ))}
              </section>
            ))}
          </div>
        )}
        {activity && samples && !!samples.cases.length && (
          <div className="viz-test-input">
            <label>
              Walkthrough input
              <select
                disabled={busy || loading}
                value={samples.selected_case}
                onChange={(event) => void selectInput(event.target.value)}
              >
                <option value="original">Sample as written</option>
                {samples.cases.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
            <span>
              The displayed sample includes these public test inputs. Expected
              answers and grading files are not loaded.
            </span>
          </div>
        )}
        {error && (
          <div className="viz-alert error" role="alert">
            {error}
          </div>
        )}
        {loading ? (
          <div className="viz-loading" role="status">
            Opening sample answers…
          </div>
        ) : activity && !samples ? (
          <button onClick={onBack}>Return to exercise</button>
        ) : (
          <>
            <div className="viz-workbench">
              <section className="viz-code-panel" aria-label="Python program">
                <div className="viz-panel-heading">
                  <div>
                    <Code2 size={18} />
                    <strong>
                      {activity ? "Sample answer" : example.title}
                    </strong>
                  </div>
                  {activity && samples && samples.samples.length > 1 ? (
                    <select
                      aria-label="Sample answer"
                      disabled={busy}
                      value={samplePath}
                      onChange={(e) => {
                        clearTrace();
                        setSamplePath(e.target.value);
                        setSource(
                          samples.samples.find(
                            (row) => row.path === e.target.value,
                          )!.source,
                        );
                      }}
                    >
                      {samples.samples.map((row) => (
                        <option key={row.path}>{row.path}</option>
                      ))}
                    </select>
                  ) : (
                    <small>
                      {activity
                        ? samplePath
                        : customSandbox?.sandbox_name || "Python"}
                    </small>
                  )}
                  {!activity && customSandbox && canEditLibrary && (
                    <button
                      className="viz-reset"
                      disabled={busy || !!authoring}
                      onClick={() => {
                        setSavedNotice("");
                        setAuthoring("edit");
                      }}
                    >
                      <SquarePen size={15} /> Edit sandbox
                    </button>
                  )}
                  {!activity && (
                    <button
                      className="viz-reset"
                      type="button"
                      title="Restore the selected example code"
                      aria-label="Reset code to the selected example"
                      disabled={
                        busy || !!authoring || source === example.source
                      }
                      onClick={() => {
                        setSource(example.source);
                        clearTrace();
                      }}
                    >
                      <RotateCcw size={15} />
                      Reset
                    </button>
                  )}
                </div>
                <Suspense
                  fallback={<div className="viz-loading">Opening editor…</div>}
                >
                  <EditorPane
                    path={`visualizer/${courseId}/${activity || exampleId}/${samplePath || "example.py"}`}
                    value={source}
                    onChange={(text) => {
                      setSource(text);
                      clearTrace();
                    }}
                    disabled={busy || !!trace || !!activity || !!authoring}
                    theme="light"
                    height="440px"
                    activeLine={step && !done ? step.line : undefined}
                    ariaLabel={
                      activity
                        ? "Read-only sample answer"
                        : "Visualization Python code"
                    }
                  />
                </Suspense>
                <div className="viz-build">
                  <button
                    className="primary"
                    disabled={busy || !!authoring || !source.trim()}
                    onClick={() => void buildTrace()}
                  >
                    <Play size={16} />
                    {busy
                      ? "Building trace…"
                      : trace
                        ? "Rebuild trace"
                        : "Visualize code"}
                  </button>
                  {trace && !activity && (
                    <button onClick={clearTrace}>
                      <SquarePen size={16} />
                      Edit code
                    </button>
                  )}
                  <span role="status">
                    {busy
                      ? phase
                      : trace
                        ? `${trace.steps.length} snapshots recorded`
                        : "Runs in an isolated Python container"}
                  </span>
                </div>
              </section>
              <section className="viz-state-panel" aria-label="Execution state">
                <div className="viz-panel-heading">
                  <div>
                    <Layers size={18} />
                    <strong>Execution state</strong>
                  </div>
                  <small>
                    {step ? (done ? "Finished" : `Line ${step.line}`) : "Ready"}
                  </small>
                </div>
                {!step ? (
                  <div className="viz-empty">
                    <Braces size={40} />
                    <h2>Follow the values</h2>
                    <p>
                      {activity
                        ? "Build a trace to see how the sample answer works."
                        : example.description}
                    </p>
                    <p>
                      {activity
                        ? "Variables, objects, and output appear here as you step through the program."
                        : example.focus}
                    </p>
                  </div>
                ) : (
                  <>
                    <div className="viz-step-caption" aria-live="polite">
                      <strong>
                        {done
                          ? "Program finished"
                          : step.event === "return"
                            ? "Returning from a call"
                            : step.event === "exception"
                              ? `${step.exception} raised`
                              : `Line ${step.line} runs next`}
                      </strong>
                      <span>Values reflect the code executed so far.</span>
                      {step.returned && (
                        <div className="viz-return">
                          Return value {value(step.returned, step.heap)}
                        </div>
                      )}
                    </div>
                    <div className="viz-state-scroll">
                      <div className="viz-section-label">
                        Call stack{" "}
                        <span>
                          {step.frames.length} frame
                          {step.frames.length === 1 ? "" : "s"}
                        </span>
                      </div>
                      <div className="viz-frames">
                        {step.frames.map((frame, frameIndex) => (
                          <article
                            className={`viz-frame ${frameIndex === step.frames.length - 1 ? "active" : ""}`}
                            key={`${frameIndex}-${frame.name}`}
                          >
                            <header>
                              <strong>
                                {frame.name === "<module>"
                                  ? "Global variables"
                                  : `${frame.name}()`}
                              </strong>
                              <small>Line {frame.line}</small>
                            </header>
                            {Object.keys(frame.locals).length ? (
                              Object.entries(frame.locals).map(
                                ([name, item]) => {
                                  const changed =
                                    !!previous &&
                                    JSON.stringify(
                                      previous.frames[frameIndex]?.locals[name],
                                    ) !== JSON.stringify(item);
                                  return (
                                    <div
                                      className={`viz-variable ${changed ? "changed" : ""}`}
                                      key={name}
                                    >
                                      <code>{name}</code>
                                      {value(item, step.heap)}
                                      {changed && (
                                        <small className="viz-change">
                                          Changed
                                        </small>
                                      )}
                                    </div>
                                  );
                                },
                              )
                            ) : (
                              <p>No variables yet.</p>
                            )}
                          </article>
                        ))}
                      </div>
                      {!!Object.keys(step.heap).length && (
                        <>
                          <div className="viz-section-label">
                            Objects & collections{" "}
                            <span>References point to the same object</span>
                          </div>
                          <div className="viz-heap">
                            {Object.entries(step.heap).map(([id, item]) => (
                              <article
                                className={`viz-object ${focused === id ? "focused" : ""}`}
                                key={id}
                              >
                                <header>
                                  <strong>{item.type}</strong>
                                  <span>#{id}</span>
                                </header>
                                {item.items.length ? (
                                  <div
                                    className={`viz-items ${["list", "tuple", "set", "frozenset"].includes(item.type) ? "sequence" : ""}`}
                                  >
                                    {item.items.map(([key, child], n) => (
                                      <div
                                        className={
                                          previous &&
                                          JSON.stringify(
                                            previous.heap[id]?.items[n],
                                          ) !== JSON.stringify([key, child])
                                            ? "item-changed"
                                            : ""
                                        }
                                        key={n}
                                      >
                                        <span>
                                          {typeof key === "string" ? (
                                            <code>{key}</code>
                                          ) : (
                                            value(key, step.heap)
                                          )}
                                        </span>
                                        <span>{value(child, step.heap)}</span>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <p>Empty</p>
                                )}
                                {item.truncated && (
                                  <small>First 20 items shown.</small>
                                )}
                              </article>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                  </>
                )}
              </section>
            </div>
            {trace && (
              <div className="viz-replay">
                <div className="viz-controls">
                  <button
                    aria-label="First step"
                    disabled={!index}
                    onClick={() => {
                      setPlaying(false);
                      setIndex(0);
                    }}
                  >
                    <RotateCcw size={17} />
                  </button>
                  <button
                    aria-label="Previous step"
                    disabled={!index}
                    onClick={() => {
                      setPlaying(false);
                      setIndex((n) => n - 1);
                    }}
                  >
                    <ChevronLeft size={20} />
                  </button>
                  <button
                    className="primary"
                    disabled={trace.steps.length < 2}
                    aria-label={playing ? "Pause replay" : "Play replay"}
                    onClick={() => {
                      if (final) setIndex(0);
                      setPlaying(!playing);
                    }}
                  >
                    {playing ? <Pause size={18} /> : <Play size={18} />}
                    <span>{playing ? "Pause" : "Play"}</span>
                  </button>
                  <button
                    aria-label="Next step"
                    disabled={final || !trace.steps.length}
                    onClick={() => {
                      setPlaying(false);
                      setIndex((n) => n + 1);
                    }}
                  >
                    <ChevronRight size={20} />
                  </button>
                </div>
                <label className="viz-scrubber">
                  Step {trace.steps.length ? index + 1 : 0} /{" "}
                  {trace.steps.length}
                  <input
                    aria-label="Execution step"
                    type="range"
                    min={0}
                    max={Math.max(0, trace.steps.length - 1)}
                    value={index}
                    disabled={!trace.steps.length}
                    onChange={(e) => {
                      setPlaying(false);
                      setIndex(Number(e.target.value));
                    }}
                  />
                </label>
                <label className="viz-speed">
                  Speed
                  <select
                    value={delay}
                    onChange={(e) => setDelay(Number(e.target.value))}
                  >
                    <option value={1600}>Slow</option>
                    <option value={900}>Normal</option>
                    <option value={350}>Fast</option>
                  </select>
                </label>
              </div>
            )}
            {trace && (trace.truncated || trace.status !== "ok") && (
              <div className="viz-alert" role="status">
                {trace.truncated
                  ? "This preview reached its snapshot limit. Use a smaller example or fewer loop iterations to see the rest."
                  : trace.status === "timeout"
                    ? "Execution was stopped at the time limit. Check the loop's stopping condition."
                    : trace.status === "output_limit"
                      ? "Execution stopped because the program printed too much output."
                      : "The program encountered an error. You can inspect earlier steps and read the error below."}
              </div>
            )}
            <section className="viz-output">
              <div className="viz-panel-heading">
                <strong>Output</strong>
                <small>{trace ? "At the selected step" : "Not run yet"}</small>
              </div>
              <pre aria-label="Program output">
                {(final ? trace?.stdout : step?.stdout) || "No output yet."}
              </pre>
            </section>
            <p className="viz-footnote">
              Traces show up to 220 snapshots, 20 items per collection, and 8
              stack frames. Imported library internals are skipped. These
              examples are for exploration and do not earn points.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
