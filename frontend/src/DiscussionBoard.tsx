import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ArrowLeft, Bold, Bookmark, Check, ChevronDown, ChevronUp, Code2, Eye, Filter, Italic, Link2, List, ListOrdered, LockKeyhole, MessageCircle, Paperclip, Pin, Plus, Quote, Search, Send, Star, ThumbsUp, Trash2 } from "lucide-react";
import BrandLogo from "./BrandLogo";
import LogoutButton from "./LogoutButton";
import DiscussionSelect from "./DiscussionSelect";
import { api, download, upload } from "./api";
import { routeHref } from "./navigation";
import "./discussionBoard.css";

type Folder = { id: number; name: string; position: number };
type Attachment = { id: number; name: string; size: number; mine: boolean };
type Settings = { allow_student_posts: boolean; allow_student_notes: boolean; allow_student_polls: boolean; allow_anonymous: boolean; allow_anonymous_to_staff: boolean; allow_private: boolean; allow_student_answers: boolean; require_folder: boolean; reading_list_enabled: boolean; require_reading_before_posting: boolean };
type Thread = { id: number; title: string; body: string; editor_mode: "formatted" | "plain" | "markdown"; kind: "question" | "note" | "poll"; visibility: "public" | "private"; anonymous: string; author: string; mine: boolean; author_is_staff: boolean; created_at: string; updated_at: string; folders: Folder[]; pinned: boolean; reading_list: boolean; required_reading: boolean; locked: boolean; endorsed: boolean; history_hidden: boolean; history_count: number; reply_count: number; unresolved_count: number; view_count: number; like_count: number; has_student_answer: boolean; has_instructor_answer: boolean; student_answer_endorsed: boolean; read: boolean; bookmarked: boolean; following: boolean; archived: boolean; liked: boolean; search_match: { source: string; excerpt: string; score: number } | null };
type Reply = { id: number; parent_id: number | null; body: string; author: string; author_is_staff: boolean; mine: boolean; resolved: boolean; created_at: string; like_count: number; liked: boolean; attachments: Attachment[] };
type Answer = { body: string; author: string; endorsed: boolean; updated_at: string };
type Detail = { thread: Thread; answers: Partial<Record<"student" | "instructor", Answer>>; replies: Reply[]; has_more_replies: boolean; poll_options: { id: number; label: string; votes_count: number }[]; my_vote: number | null; attachments: Attachment[] };
type Tab = "qa" | "resources" | "statistics" | "manage";
type Draft = { title: string; body: string; editor_mode: Thread["editor_mode"]; kind: Thread["kind"]; visibility: Thread["visibility"]; anonymous: string; folder_ids: number[]; options: string[]; updated_at?: string };
const date = (iso: string) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
const initials = (name: string) => name === "Anonymous" ? "?" : name.split(/\s+/).slice(0, 2).map(part => part[0]?.toUpperCase()).join("");
const discussionLink = (post: number, followup: number | null = null) => `${location.origin}${location.pathname}${routeHref({ page: "discussions", post, followup })}`;
const feedGroup = (thread: Thread) => thread.pinned ? "Pinned" : thread.reading_list ? "Reading list" : "All posts";

function InlineText({ text }: { text: string }) {
  return <>{text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*")) return <em key={index}>{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noopener noreferrer">{link[1]}</a>;
    return part;
  })}</>;
}

function PostBody({ text, mode = "formatted" }: { text: string; mode?: Thread["editor_mode"] }) {
  if (mode === "plain") return <div className="db-copy"><p>{text}</p></div>;
  const parts = text.split(/(```[\w+-]*\n[\s\S]*?```)/g);
  return <div className="db-copy">{parts.map((part, index) => {
    if (part.startsWith("```")) return <pre key={index}><code>{part.replace(/^```[\w+-]*\n/, "").replace(/```$/, "")}</code></pre>;
    return part.split(/\n\s*\n/).filter(Boolean).map((block, blockIndex) => {
      const lines = block.split("\n");
      if (lines.every(line => /^\s*- /.test(line))) return <ul key={`${index}-${blockIndex}`}>{lines.map((line, lineIndex) => <li key={lineIndex}><InlineText text={line.replace(/^\s*- /, "")} /></li>)}</ul>;
      if (lines.every(line => /^\s*\d+\. /.test(line))) return <ol key={`${index}-${blockIndex}`}>{lines.map((line, lineIndex) => <li key={lineIndex}><InlineText text={line.replace(/^\s*\d+\. /, "")} /></li>)}</ol>;
      if (lines.every(line => /^> /.test(line))) return <blockquote key={`${index}-${blockIndex}`}>{lines.map((line, lineIndex) => <span key={lineIndex}><InlineText text={line.slice(2)} /><br /></span>)}</blockquote>;
      return <p key={`${index}-${blockIndex}`}>{lines.map((line, lineIndex) => <span key={lineIndex}>{lineIndex > 0 && <br />}<InlineText text={line} /></span>)}</p>;
    });
  })}</div>;
}

function AttachmentPicker({ files, onChange }: { files: File[]; onChange: (files: File[]) => void }) {
  return <div className="db-attachment-picker">
    <label><Paperclip size={16} /> Choose files<input type="file" multiple accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.py,.ipynb" onChange={event => onChange(Array.from(event.target.files || []))} /></label>
    <small>Images, PDFs, text, Python, or notebooks · 2 MB per file</small>
    {files.length > 0 && <div className="db-pending-files">{files.map((file, index) => <span key={`${file.name}-${index}`}>{file.name}<button type="button" aria-label={`Remove ${file.name}`} onClick={() => onChange(files.filter((_, number) => number !== index))}>×</button></span>)}</div>}
  </div>;
}

export default function DiscussionBoard({ course, selectedPost, onSelectPost, onBack, onSignOut }: {
  course: string; selectedPost: number | null; onSelectPost: (post: number | null) => void;
  onBack: () => void; onSignOut: () => void;
}) {
  const [tab, setTab] = useState<Tab>("qa");
  const [staff, setStaff] = useState(false);
  const [viewerName, setViewerName] = useState("My name");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [reading, setReading] = useState({ unread: 0, required: 0 });
  const [savedDraft, setSavedDraft] = useState<Draft | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [folder, setFolder] = useState<number | null>(null);
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("recent");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [composing, setComposing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [kind, setKind] = useState<Thread["kind"]>("question");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [editorMode, setEditorMode] = useState<"formatted" | "plain" | "markdown">("formatted");
  const [preview, setPreview] = useState(false);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [chosenFolders, setChosenFolders] = useState<number[]>([]);
  const [visibility, setVisibility] = useState<"public" | "private">("public");
  const [anonymous, setAnonymous] = useState("none");
  const [options, setOptions] = useState(["", ""]);
  const [postFiles, setPostFiles] = useState<File[]>([]);
  const [answerKind, setAnswerKind] = useState<"student" | "instructor" | null>(null);
  const [answerBody, setAnswerBody] = useState("");
  const [followupBody, setFollowupBody] = useState("");
  const [followupAnonymous, setFollowupAnonymous] = useState("none");
  const [followupFiles, setFollowupFiles] = useState<File[]>([]);
  const [replyTarget, setReplyTarget] = useState<number | null>(null);
  const [stats, setStats] = useState<Record<string, any> | null>(null);
  const [folderName, setFolderName] = useState("");
  const [history, setHistory] = useState<{ version: number; title: string; body: string; editor_mode: Thread["editor_mode"]; editor_label: string; created_at: string }[] | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const reloadMeta = useCallback(async () => {
    const data = await api("discussions/meta/");
    setStaff(data.staff); setViewerName(data.viewer_name); setSettings(data.settings); setFolders(data.folders); setReading(data.reading);
  }, []);
  useEffect(() => { void reloadMeta().catch((failure: Error) => setError(failure.message)); }, [reloadMeta]);
  useEffect(() => { void api("discussions/draft/").then(data => setSavedDraft(data.draft)).catch((failure: Error) => setError(failure.message)); }, []);
  const feedPath = useCallback((offset = 0) => {
    const params = new URLSearchParams({ filter, sort, offset: String(offset) });
    if (query) params.set("q", query);
    if (folder) params.set("folder", String(folder));
    if (tab === "resources") params.set("kind", "note");
    return `discussions/?${params}`;
  }, [filter, sort, query, folder, tab]);
  const reloadFeed = useCallback(async () => {
    const data = await api(feedPath());
    setThreads(data.threads); setHasMore(data.has_more); setLoading(false);
  }, [feedPath]);
  useEffect(() => {
    if (tab !== "qa" && tab !== "resources") return;
    let current = true;
    setLoading(true);
    api(feedPath()).then(data => { if (current) { setThreads(data.threads); setHasMore(data.has_more); setLoading(false); } })
      .catch((failure: Error) => { if (current) { setError(failure.message); setLoading(false); } });
    return () => { current = false; };
  }, [feedPath, tab]);

  const reloadDetail = useCallback(async (id: number) => {
    const data = await api(`discussions/${id}/`);
    setDetail(data);
    await reloadMeta();
  }, [reloadMeta]);
  useEffect(() => {
    if (!selectedPost) { setDetail(null); return; }
    setHistory(null);
    void reloadDetail(selectedPost).catch((failure: Error) => setError(failure.message));
  }, [selectedPost, reloadDetail]);
  useEffect(() => {
    if (!detail || detail.thread.id !== selectedPost) return;
    const followup = new URLSearchParams(window.location.hash.split("?")[1] || "").get("followup");
    if (followup && /^\d+$/.test(followup)) requestAnimationFrame(() => document.getElementById(`followup-${followup}`)?.scrollIntoView({ block: "center" }));
  }, [detail, selectedPost]);
  useEffect(() => {
    if (tab !== "statistics") return;
    void api("discussions/statistics/").then(setStats).catch((failure: Error) => setError(failure.message));
  }, [tab]);

  function openComposer(thread?: Thread, draft?: Draft) {
    setError(""); setNotice(""); setComposing(true); setEditing(!!thread);
    setKind(thread?.kind || draft?.kind || (tab === "resources" ? "note" : "question")); setTitle(thread?.title || draft?.title || ""); setBody(thread?.body || draft?.body || "");
    setChosenFolders(thread?.folders.map(row => row.id) || draft?.folder_ids.filter(id => folders.some(row => row.id === id)) || []);
    setVisibility(thread?.visibility || draft?.visibility || "public"); setAnonymous(thread?.anonymous || draft?.anonymous || "none"); setOptions(draft?.options.length ? draft.options : ["", ""]);
    setEditorMode(thread?.editor_mode || draft?.editor_mode || "formatted"); setPreview(false); setPostFiles([]);
  }

  async function uploadFiles(path: string, files: File[]) {
    const failed: string[] = [];
    for (const file of files) {
      const data = new FormData(); data.append("file", file);
      try { await upload(path, data); } catch { failed.push(file.name); }
    }
    return failed;
  }
  function formatBody(before: string, after = "", placeholder = "text") {
    const field = bodyRef.current;
    if (!field) return;
    const start = field.selectionStart, end = field.selectionEnd;
    const selection = body.slice(start, end) || placeholder;
    setBody(body.slice(0, start) + before + selection + after + body.slice(end));
    requestAnimationFrame(() => { field.focus(); field.setSelectionRange(start + before.length, start + before.length + selection.length); });
  }
  async function saveDraft() {
    setBusy(true); setError("");
    try {
      const draft = { title, body, editor_mode: editorMode, kind, visibility, anonymous, folder_ids: chosenFolders, options: kind === "poll" ? options : [] };
      const result = await api("discussions/draft/save/", draft);
      setSavedDraft({ ...draft, updated_at: result.updated_at }); setComposing(false); setNotice("Draft saved. You can resume it from New post.");
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function submitPost(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      let failedFiles: string[] = [];
      if (editing && detail) {
        await api(`discussions/${detail.thread.id}/edit/`, { title, body, editor_mode: editorMode, folder_ids: chosenFolders, visibility, anonymous });
        failedFiles = await uploadFiles(`discussions/${detail.thread.id}/attachments/`, postFiles);
        await reloadDetail(detail.thread.id); setNotice("Post updated.");
      } else {
        const data = await api("discussions/new/", { title, body, editor_mode: editorMode, kind, visibility, anonymous,
          folder_ids: chosenFolders, options: kind === "poll" ? options : [] });
        failedFiles = await uploadFiles(`discussions/${data.thread.id}/attachments/`, postFiles);
        onSelectPost(data.thread.id); setSavedDraft(null); setNotice("Post published.");
      }
      setPostFiles([]); setComposing(false); setEditing(false); await reloadFeed();
      if (failedFiles.length) setError(`The post was saved, but ${failedFiles.join(", ")} could not be attached.`);
    } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function act(action: string, value: boolean) {
    if (!detail) return;
    setBusy(true); setError("");
    try { await api(`discussions/${detail.thread.id}/action/`, { action, value });
      if (action === "read" && !value) setDetail(old => old ? { ...old, thread: { ...old.thread, read: false } } : old);
      else await reloadDetail(detail.thread.id);
      await reloadFeed(); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function postFollowup(event: FormEvent) {
    event.preventDefault(); if (!detail) return;
    setBusy(true); setError("");
    try { const data = await api(`discussions/${detail.thread.id}/replies/`, { body: followupBody, parent_id: replyTarget, anonymous: followupAnonymous });
      const failedFiles = await uploadFiles(`discussions/replies/${data.reply.id}/attachments/`, followupFiles);
      setFollowupBody(""); setFollowupAnonymous("none"); setFollowupFiles([]); setReplyTarget(null); await reloadDetail(detail.thread.id); await reloadFeed();
      if (failedFiles.length) setError(`The reply was posted, but ${failedFiles.join(", ")} could not be attached.`); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function replyAction(id: number, action: string, value: boolean) {
    if (!detail) return;
    try { await api(`discussions/replies/${id}/action/`, { action, value }); await reloadDetail(detail.thread.id); await reloadFeed(); }
    catch (failure) { setError((failure as Error).message); }
  }
  async function removeAttachment(id: number) {
    if (!detail) return;
    try { await api(`discussions/attachments/${id}/remove/`, {}); await reloadDetail(detail.thread.id); }
    catch (failure) { setError((failure as Error).message); }
  }
  async function submitAnswer(event: FormEvent) {
    event.preventDefault(); if (!detail || !answerKind) return;
    setBusy(true); setError("");
    try { await api(`discussions/${detail.thread.id}/answer/`, { kind: answerKind, body: answerBody });
      setAnswerKind(null); setAnswerBody(""); await reloadDetail(detail.thread.id); await reloadFeed(); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function manageFolder(action: string, extra: Record<string, unknown>) {
    try { const data = await api("discussions/folders/", { action, ...extra });
      setFolders(data.folders); setFolderName(""); setNotice("Folders updated."); }
    catch (failure) { setError((failure as Error).message); }
  }
  async function saveSetting(key: keyof Settings, value: boolean) {
    try { const data = await api("discussions/settings/", { [key]: value }); setSettings(data.settings); setNotice("Board settings saved."); }
    catch (failure) { setError((failure as Error).message); }
  }

  const current = detail?.thread;
  const roots = detail?.replies.filter(row => row.parent_id === null) || [];
  const boardTabs: { id: Tab; label: string }[] = [{ id: "qa", label: "Q&A" }, { id: "resources", label: "Resources" }, { id: "statistics", label: staff ? "Statistics" : "My activity" }, ...(staff ? [{ id: "manage" as Tab, label: "Manage board" }] : [])];
  const canPost = staff || !!settings?.allow_student_posts && (tab !== "resources" || !!settings?.allow_student_notes);
  const postingBlocked = !staff && !!settings?.reading_list_enabled && !!settings?.require_reading_before_posting && reading.required > 0;
  const attachmentList = (items: Attachment[], compact = false) => items.length > 0 && <div className={`db-attachments ${compact ? "compact" : ""}`}>
    {!compact && <strong>Attachments</strong>}
    {items.map(item => <div key={item.id}><Paperclip size={13} /><button className="db-attachment-download" onClick={async () => { try { await download(`discussions/attachments/${item.id}/`, item.name); } catch (failure) { setError((failure as Error).message); } }}>{item.name}</button><small>{Math.max(1, Math.ceil(item.size / 1024))} KB</small>{(staff || item.mine) && <button onClick={() => void removeAttachment(item.id)}>Remove</button>}</div>)}
  </div>;
  const filters = [{ id: "all", label: "All posts" }, { id: "unread", label: "Unread" }, { id: "unresolved", label: "Unresolved" }, { id: "following", label: "Following" }, { id: "bookmarked", label: "Bookmarked" }, { id: "reading", label: "Reading list" }, { id: "mine", label: "My posts" }, { id: "instructor", label: "Instructor posts" }, { id: "archived", label: "Archived" }];

  return <div className="discussion-shell">
    <header className="discussion-topbar"><div className="brand"><BrandLogo /></div><strong className="db-course-name">{course}</strong>
      <nav className="db-topnav" aria-label="Discussion sections">{boardTabs.map(item => <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => { setTab(item.id); setComposing(false); }}>{item.label}</button>)}</nav>
      <div className="discussion-topbar-actions"><button className="discussion-home-link" onClick={onBack}><ArrowLeft size={17} /> Course home</button><LogoutButton onConfirm={onSignOut} /></div>
    </header>
    {(tab === "qa" || tab === "resources") && <div className="db-folderbar"><button className={folder === null ? "active" : ""} onClick={() => setFolder(null)}>All folders</button>{folders.map(row => <button key={row.id} className={folder === row.id ? "active" : ""} onClick={() => setFolder(row.id)}>{row.name}</button>)}</div>}
    {error && <div className="db-banner error" role="alert">{error}<button onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
    {notice && <div className="db-banner success" role="status">{notice}<button onClick={() => setNotice("")} aria-label="Dismiss notice">×</button></div>}

    {(tab === "qa" || tab === "resources") ? <div className="db-workspace">
      <aside className="db-feed">
        <div className="db-feed-actions"><button className="db-new" disabled={!canPost} onClick={() => openComposer()}><Plus size={17} /> New post</button><form className="db-search-field" role="search" onSubmit={event => { event.preventDefault(); setQuery(search.trim()); }} onClick={() => searchRef.current?.focus()}><Search size={17} aria-hidden="true" /><input ref={searchRef} type="search" aria-label="Search posts, answers, and followups" placeholder="Search posts, answers, and followups…" value={search} onChange={event => setSearch(event.target.value)} />{search && <button type="button" className="db-search-clear" aria-label="Clear search" onClick={() => { setSearch(""); setQuery(""); }}>×</button>}</form></div>
        {savedDraft && <button className="db-resume-draft" onClick={() => { setTab("qa"); openComposer(undefined, savedDraft); }}>Resume saved draft <span>{date(savedDraft.updated_at || new Date().toISOString())}</span></button>}
        <div className="db-feed-controls"><Filter size={16} /><DiscussionSelect label="Filter posts" compact value={filter} options={filters.map(row => ({ value: row.id, label: row.label }))} onChange={setFilter} />{query ? <span className="db-relevance-sort">Best matches</span> : <DiscussionSelect label="Sort posts" compact value={sort} options={[{value:"recent",label:"Recently active"},{value:"newest",label:"Newest"},{value:"oldest",label:"Oldest"}]} onChange={setSort} />}</div>
        <div className="db-feed-scroll">{loading ? <p className="db-empty">Loading posts…</p> : threads.length === 0 ? <p className="db-empty">No posts match this view. {canPost ? "Start a new post or choose another filter." : "Try another filter."}</p> : threads.map((row, index) =>
          <button key={row.id} className={`db-feed-item ${selectedPost === row.id ? "selected" : ""} ${!row.read ? "unread" : ""}`} onClick={() => { setComposing(false); onSelectPost(row.id); }}>
            {!query && filter === "all" && sort === "recent" && (index === 0 || feedGroup(row) !== feedGroup(threads[index - 1])) && <span className="db-feed-group">{feedGroup(row)}</span>}
            <span className="db-feed-item-top"><span>{row.pinned && <Pin size={13} />}<b>{row.kind === "question" ? "Q" : row.kind === "note" ? "N" : "P"}</b>{row.author_is_staff && <em>Instr</em>}{row.visibility === "private" && <em>Private</em>}</span><time>{date(row.updated_at)}</time></span>
            <strong>{row.title}</strong>{row.search_match ? <><span className="db-search-source">Matched in {row.search_match.source}</span><span className="db-feed-preview">{row.search_match.excerpt}</span></> : <span className="db-feed-preview">{row.body}</span>}
            <span className="db-feed-item-bottom">{row.folders.map(folder => <i key={folder.id}>{folder.name}</i>)}{row.has_instructor_answer && <i className="answer">Instructor answer</i>}{row.student_answer_endorsed && <i className="answer">Endorsed answer</i>}{row.unresolved_count > 0 && <i className="unresolved">{row.unresolved_count} unresolved</i>}{row.required_reading && <i className="reading">Required reading</i>}{row.reading_list && !row.required_reading && <i className="reading">Reading list</i>}<small><MessageCircle size={13} />{row.reply_count}</small></span>
          </button>)}
          {hasMore && <button className="db-load" disabled={busy} onClick={async () => { try { const data = await api(feedPath(threads.length)); setThreads(old => [...old, ...data.threads]); setHasMore(data.has_more); } catch (failure) { setError((failure as Error).message); } }}>Load more posts</button>}
        </div>
      </aside>

      <main className="db-detail">
        {composing ? <form className="db-composer" onSubmit={submitPost}>
          <div className="db-detail-top"><button type="button" onClick={() => setComposing(false)}><ArrowLeft size={17} /> Back</button></div>
          <h1>{editing ? "Edit post" : "New post"}</h1>
          {postingBlocked && <div className="db-posting-gate" role="alert">You're unable to post until you've read {reading.required} required {reading.required === 1 ? "item" : "items"} in your reading list. <button type="button" onClick={() => { setComposing(false); setTab("qa"); setFilter("reading"); }}>View reading list ({reading.unread} unread)</button></div>}
          {!editing && <div className="db-composer-row"><span className="db-composer-label">Post type <b>*</b></span><div className="db-post-types" role="group" aria-label="Post type">{(tab === "resources" ? ["note"] as const : ["question", "note", "poll"] as const).map(value => <button type="button" key={value} className={kind === value ? "selected" : ""} disabled={!staff && (value === "note" && !settings?.allow_student_notes || value === "poll" && !settings?.allow_student_polls)} onClick={() => setKind(value)}><span className="db-radio-dot" /> <strong>{value === "question" ? "Question" : value === "note" ? "Note" : "Poll / in-class response"}</strong><small>{value === "question" ? "If you need an answer" : value === "note" ? "If you don't need an answer" : "If you need a vote"}</small></button>)}</div></div>}
          <div className="db-composer-row"><span className="db-composer-label">Post to <b>*</b></span><div className="db-radio-group" role="group" aria-label="Post to"><label><input type="radio" name="visibility" checked={visibility === "public"} onChange={() => setVisibility("public")} /> Entire class</label>{(staff || settings?.allow_private) && <label><input type="radio" name="visibility" checked={visibility === "private"} onChange={() => setVisibility("private")} /> Instructor(s)</label>}</div></div>
          {folders.length > 0 && <div className="db-composer-row"><span className="db-composer-label">Select folders {settings?.require_folder && <b>*</b>}</span><div className="db-folder-choices">{folders.map(row => <label key={row.id} className={chosenFolders.includes(row.id) ? "selected" : ""}><input type="checkbox" checked={chosenFolders.includes(row.id)} onChange={event => setChosenFolders(old => event.target.checked ? [...old, row.id] : old.filter(id => id !== row.id))} />{row.name}</label>)}</div></div>}
          <div className="db-composer-row"><label className="db-composer-label" htmlFor="db-post-title">Summary <b>*</b></label><div className="db-summary-field"><input id="db-post-title" autoFocus maxLength={100} required value={title} onChange={event => setTitle(event.target.value)} placeholder="Enter a one-line summary, 100 characters or less" /><small>{title.length}/100</small></div></div>
          <div className="db-composer-row db-editor-row"><span className="db-composer-label">Details <b>*</b></span><div className="db-editor-area"><div className="db-editor-modes" role="group" aria-label="Editor mode">{([['formatted','Formatted'],['plain','Plain text'],['markdown','Markdown']] as const).map(([value,label]) => <label key={value}><input type="radio" name="editorMode" checked={editorMode === value} onChange={() => { setEditorMode(value); setPreview(false); }} /> {label}</label>)}<button type="button" className={preview ? "active" : ""} aria-pressed={preview} onClick={() => setPreview(value => !value)}>Preview {preview ? "on" : "off"}</button></div>{editorMode === "formatted" && !preview && <div className="db-format-toolbar" role="toolbar" aria-label="Formatting"><button type="button" title="Bold" onClick={() => formatBody("**", "**")}><Bold size={17} /></button><button type="button" title="Italic" onClick={() => formatBody("*", "*")}><Italic size={17} /></button><button type="button" title="Bulleted list" onClick={() => formatBody("- ", "", "item")}><List size={17} /></button><button type="button" title="Numbered list" onClick={() => formatBody("1. ", "", "item")}><ListOrdered size={17} /></button><button type="button" title="Link" onClick={() => formatBody("[", "](https://example.com)", "link text")}><Link2 size={17} /></button><button type="button" title="Code block" onClick={() => formatBody("```\n", "\n```", "code")}><Code2 size={17} /></button><button type="button" title="Quote" onClick={() => formatBody("> ", "", "quote")}><Quote size={17} /></button></div>}{preview ? <div className="db-editor-preview">{body.trim() ? <PostBody text={body} mode={editorMode} /> : <p>Your post will appear here.</p>}</div> : <textarea ref={bodyRef} maxLength={10000} required rows={11} value={body} onChange={event => setBody(event.target.value)} placeholder={editorMode === "plain" ? "Write the details of your post…" : "Write the details of your post. Use the toolbar or Markdown formatting."} />}{editorMode === "formatted" && <small className="db-editor-help">The toolbar adds Markdown formatting. Use Preview to see the result.</small>}</div></div>
          {!editing && kind === "poll" && <div className="db-composer-row"><span className="db-composer-label">Poll choices <b>*</b></span><div className="db-poll-choices">{options.map((option, index) => <input key={index} maxLength={240} required value={option} onChange={event => setOptions(old => old.map((value, number) => number === index ? event.target.value : value))} placeholder={`Choice ${index + 1}`} />)}<button type="button" disabled={options.length >= 8} onClick={() => setOptions(old => [...old, ""])}>Add choice</button></div></div>}
          <div className="db-composer-row"><span className="db-composer-label">Attachments</span><AttachmentPicker files={postFiles} onChange={setPostFiles} /></div>
          <div className="db-composer-row"><span className="db-composer-label">Show my name as</span><DiscussionSelect label="Show my name as" value={anonymous} onChange={setAnonymous} options={[{value:"none",label:viewerName},...(staff || settings?.allow_anonymous ? [{value:"classmates",label:"Anonymous to classmates"}] : []),...(staff || settings?.allow_anonymous && settings?.allow_anonymous_to_staff ? [{value:"everyone",label:"Anonymous to everyone"}] : [])]} /></div>
          <div className="db-composer-actions"><button className="db-primary" disabled={busy || postingBlocked || !title.trim() || !body.trim() || !!settings?.require_folder && chosenFolders.length === 0}><Send size={16} />{busy ? "Saving…" : editing ? "Save post" : `Post ${kind} to ${visibility === "public" ? "class" : "instructors"}`}</button>{!editing && <button type="button" onClick={() => void saveDraft()} disabled={busy}>Save draft</button>}<button type="button" onClick={() => setComposing(false)}>Cancel</button>{savedDraft && !editing && <button type="button" className="db-discard-draft" onClick={async () => { try { await api("discussions/draft/discard/", {}); setSavedDraft(null); setNotice("Saved draft discarded."); } catch (failure) { setError((failure as Error).message); } }}>Discard saved draft</button>}</div>
        </form> : current ? <>
          <div className="db-detail-top"><span>{current.kind === "question" ? "Question" : current.kind === "note" ? "Note" : "Poll"} <b>#{current.id}</b></span><div>{(current.history_count > 1 && (!current.history_hidden || staff)) && <button onClick={async () => { if (history) { setHistory(null); return; } try { const data = await api(`discussions/${current.id}/history/`); setHistory(data.revisions); setHistoryVersion(data.revisions.length - 1); } catch (failure) { setError((failure as Error).message); } }}>History</button>}<button title="Copy link" onClick={async () => { await navigator.clipboard.writeText(discussionLink(current.id)); setNotice("Link copied."); }}>Copy link</button></div></div>
          {history && <div className="db-history"><strong>Post history</strong><div>{history.map((revision, index) => <button key={revision.version} className={historyVersion === index ? "active" : ""} onClick={() => setHistoryVersion(index)}>v{revision.version}</button>)}</div><small>{date(history[historyVersion].created_at)} · edited by {history[historyVersion].editor_label}</small><h3>{history[historyVersion].title}</h3><PostBody text={history[historyVersion].body} mode={history[historyVersion].editor_mode} /></div>}
          <article className="db-post"><h1>{current.title}</h1><div className="db-post-meta">Posted by {current.author} · {date(current.created_at)}{current.visibility === "private" && <span>Private to instructors</span>}</div><PostBody text={current.body} mode={current.editor_mode} />
            {attachmentList(detail.attachments)}
            <div className="db-tags">{current.folders.map(row => <span key={row.id}>{row.name}</span>)}{current.pinned && <span>Pinned</span>}{current.required_reading && <span>Required reading</span>}{current.reading_list && !current.required_reading && <span>Reading list</span>}{current.endorsed && <span>Instructor endorsed</span>}{current.locked && <span><LockKeyhole size={13} /> Locked</span>}</div>
            <div className="db-post-actions"><button aria-pressed={current.liked} onClick={() => void act("like", !current.liked)}><ThumbsUp size={18} /> {current.like_count}</button><button aria-pressed={current.bookmarked} title={current.bookmarked ? "Remove bookmark" : "Bookmark"} onClick={() => void act("bookmark", !current.bookmarked)}><Bookmark size={18} /></button><button aria-pressed={current.following} title={current.following ? "Unfollow" : "Follow"} onClick={() => void act("follow", !current.following)}><Star size={18} /></button><button title="Copy post link" onClick={async () => { await navigator.clipboard.writeText(discussionLink(current.id)); setNotice("Link copied."); }}><Link2 size={18} /></button><span><Eye size={15} /> {current.view_count} views</span></div>
          </article>
          <div className="db-post-menu"><button onClick={() => void act("read", false)}>Mark unread</button><button onClick={() => void act("archive", !current.archived)}>{current.archived ? "Restore" : "Archive"}</button>{(staff || current.mine) && <button onClick={() => openComposer(current)}>Edit post</button>}{staff && <><button onClick={() => void act("pin", !current.pinned)}>{current.pinned ? "Unpin" : "Pin"}</button><button onClick={() => void act("reading_list", !current.reading_list)} disabled={!settings?.reading_list_enabled}>{current.reading_list ? "Remove from reading list" : "Add to reading list"}</button><button onClick={() => void act("required_reading", !current.required_reading)} disabled={!settings?.reading_list_enabled || current.visibility === "private"}>{current.required_reading ? "Make optional reading" : "Require reading before posting"}</button><button onClick={() => void act("lock", !current.locked)}>{current.locked ? "Unlock" : "Lock"}</button><button onClick={() => void act("endorse", !current.endorsed)}>{current.endorsed ? "Remove endorsement" : "Endorse post"}</button><button onClick={() => void act("hide_history", !current.history_hidden)}>{current.history_hidden ? "Show history" : "Hide history"}</button><button className="danger" onClick={async () => { if (!window.confirm("Remove this post from the board?")) return; try { await api(`discussions/${current.id}/delete/`, {}); onSelectPost(null); await reloadFeed(); } catch (failure) { setError((failure as Error).message); } }}><Trash2 size={14} /> Remove</button></>}</div>
          {current.kind === "question" && <div className="db-answers">{(["student", "instructor"] as const).map(answerType => { const answer = detail?.answers[answerType]; const canEdit = !current.locked || staff; const permitted = canEdit && (staff || answerType === "student" && settings?.allow_student_answers); return <section key={answerType} className={`db-answer ${answerType}`}><div className="db-answer-head"><b>{answerType === "student" ? "Students’ answer" : "Instructors’ answer"}</b>{answer?.endorsed && <span><Check size={14} /> Endorsed by instructor</span>}</div>{answer ? <><PostBody text={answer.body} /><small>Last edited by {answer.author} · {date(answer.updated_at)}</small></> : <p className="db-answer-empty">No {answerType} answer yet.</p>}{permitted && <button onClick={() => { setAnswerKind(answerType); setAnswerBody(answer?.body || ""); }}>{answer ? "Edit answer" : "Write answer"}</button>}{staff && answerType === "student" && answer && <button onClick={async () => { try { await api(`discussions/${current.id}/answer/endorse/`, { value: !answer.endorsed }); await reloadDetail(current.id); await reloadFeed(); } catch (failure) { setError((failure as Error).message); } }}>{answer.endorsed ? "Remove endorsement" : "Endorse answer"}</button>}</section>; })}</div>}
          {current.kind === "poll" && <section className="db-poll"><h2>Poll</h2>{detail?.poll_options.map(option => <button key={option.id} disabled={current.locked && !staff} className={detail.my_vote === option.id ? "voted" : ""} onClick={async () => { try { await api(`discussions/${current.id}/vote/`, { option_id: option.id }); await reloadDetail(current.id); } catch (failure) { setError((failure as Error).message); } }}><span>{option.label}</span><b>{option.votes_count} votes</b></button>)}</section>}
          <section className="db-followups"><h2><MessageCircle size={21} /> {current.reply_count} Followup {current.reply_count === 1 ? "Discussion" : "Discussions"}</h2>{roots.length === 0 && <p>No followups yet.</p>}{roots.map(root => <article className="db-followup" id={`followup-${root.id}`} key={root.id}>
            <div className="db-followup-head"><button className={root.resolved ? "resolved" : "unresolved"} disabled={!staff && !root.mine} title={staff || root.mine ? "Change resolution" : undefined} onClick={() => void replyAction(root.id, "resolve", !root.resolved)}><Check size={14} /> {root.resolved ? "Resolved" : "Unresolved"}</button><div><span>#{current.id}_f{root.id}</span><button title="Copy followup link" onClick={async () => { await navigator.clipboard.writeText(discussionLink(current.id, root.id)); setNotice("Followup link copied."); }}><Link2 size={16} /></button></div></div>
            <div className="db-followup-person"><span className="db-avatar">{initials(root.author)}</span><div><strong>{root.author}</strong>{root.author_is_staff && <em>Instructor</em>}<small>{date(root.created_at)}</small></div></div>
            <div className="db-followup-copy"><PostBody text={root.body} />{attachmentList(root.attachments, true)}</div><div className="db-followup-actions"><button onClick={() => void replyAction(root.id, "like", !root.liked)} aria-pressed={root.liked} title="Like followup"><ThumbsUp size={16} /> {root.like_count}</button>{(staff || root.mine) && <button onClick={() => void replyAction(root.id, "delete", true)}>Remove</button>}</div>
            <div className="db-comment-thread">{detail.replies.filter(comment => comment.parent_id === root.id).map(comment => <div className="db-comment" key={comment.id}><div className="db-followup-person"><span className="db-avatar">{initials(comment.author)}</span><div><strong>{comment.author}</strong>{comment.author_is_staff && <em>Instructor</em>}<small>{date(comment.created_at)}</small></div></div><PostBody text={comment.body} />{attachmentList(comment.attachments, true)}<div className="db-followup-actions"><button onClick={() => void replyAction(comment.id, "like", !comment.liked)} aria-pressed={comment.liked} title="Like reply"><ThumbsUp size={15} /> {comment.like_count}</button>{(staff || comment.mine) && <button onClick={() => void replyAction(comment.id, "delete", true)}>Remove</button>}</div></div>)}</div>
            <button className="db-reply-link" onClick={() => { setReplyTarget(root.id); setFollowupBody(""); setFollowupFiles([]); requestAnimationFrame(() => document.getElementById("db-followup-compose")?.scrollIntoView({ behavior: "smooth", block: "center" })); }}>↩ Reply</button>
          </article>)}
            {detail?.has_more_replies && <button className="db-load" onClick={async () => { const data = await api(`discussions/${current.id}/?offset=${detail.replies.length}`); setDetail(old => old && ({ ...old, replies: [...old.replies, ...data.replies], has_more_replies: data.has_more_replies })); }}>Load more followups</button>}
            {(!current.locked || staff) && <form id="db-followup-compose" onSubmit={postFollowup}><label>{replyTarget ? "Reply to followup" : "New followup"}<textarea required maxLength={10000} rows={4} value={followupBody} onChange={event => setFollowupBody(event.target.value)} placeholder="Add a question or comment…" /></label><AttachmentPicker files={followupFiles} onChange={setFollowupFiles} /><div>{(staff || settings?.allow_anonymous) && <div className="db-followup-name"><span>Show my name</span><DiscussionSelect label="Followup name visibility" compact value={followupAnonymous} onChange={setFollowupAnonymous} options={[{value:"none",label:"To everyone"},{value:"classmates",label:"Only to instructors"},...(staff || settings?.allow_anonymous && settings?.allow_anonymous_to_staff ? [{value:"everyone",label:"To no one"}] : [])]} /></div>}{replyTarget && <button type="button" onClick={() => { setReplyTarget(null); setFollowupFiles([]); }}>Cancel</button>}<button className="db-primary" disabled={busy || !followupBody.trim()}><Send size={15} /> Post {replyTarget ? "reply" : "followup"}</button></div></form>}
          </section>
        </> : <div className="db-placeholder"><MessageCircle size={38} /><h2>Choose a post</h2><p>Read a question, share an answer, or start a new post.</p></div>}
      </main>
    </div> : tab === "manage" && staff && settings ? <main className="db-manage"><div><span className="db-eyebrow">INSTRUCTOR TOOLS</span><h1>Manage discussion board</h1><p>Choose how your class can ask questions and organize posts.</p></div><section><h2>Posting and participation</h2>{([
      ["allow_student_posts", "Students can create posts"], ["allow_student_notes", "Students can publish notes"], ["allow_student_polls", "Students can create polls"], ["allow_anonymous", "Anonymous to classmates"], ["allow_anonymous_to_staff", "Anonymous to instructors"], ["allow_private", "Students can ask instructors privately"], ["allow_student_answers", "Students can edit the shared answer"], ["require_folder", "Require a folder for each post"], ["reading_list_enabled", "Enable instructor reading list"], ["require_reading_before_posting", "Students must read required items before posting"],
    ] as [keyof Settings, string][]).map(([key, label]) => <label className="db-setting" key={key}><span>{label}</span><input type="checkbox" checked={settings[key]} onChange={event => void saveSetting(key, event.target.checked)} /></label>)}</section><section><h2>Folders</h2><p>Folders appear across the top of the Q&A feed.</p><form onSubmit={event => { event.preventDefault(); void manageFolder("create", { name: folderName }); }}><input aria-label="New folder name" maxLength={60} value={folderName} onChange={event => setFolderName(event.target.value)} placeholder="New folder name" /><button className="db-primary" disabled={!folderName.trim()}>Add folder</button></form>{folders.map((row, index) => <div className="db-folder-row" key={row.id}><span>{row.name}</span><button title="Move up" disabled={index === 0} onClick={() => { const ids = folders.map(item => item.id); [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]]; void manageFolder("reorder", { ids }); }}><ChevronUp size={17} /></button><button title="Move down" disabled={index === folders.length - 1} onClick={() => { const ids = folders.map(item => item.id); [ids[index + 1], ids[index]] = [ids[index], ids[index + 1]]; void manageFolder("reorder", { ids }); }}><ChevronDown size={17} /></button><button onClick={() => { const name = window.prompt("Rename folder", row.name); if (name?.trim()) void manageFolder("rename", { id: row.id, name }); }}>Rename</button><button className="danger" onClick={() => { if (window.confirm(`Delete ${row.name}? Posts will remain, without this folder.`)) void manageFolder("delete", { id: row.id }); }}>Remove</button></div>)}</section></main> : <main className="db-stats"><span className="db-eyebrow">{staff ? "CLASS ACTIVITY" : "YOUR ACTIVITY"}</span><h1>{staff ? "Discussion statistics" : "My activity"}</h1>{staff && <button className="db-export" onClick={async () => { try { await download("discussions/statistics/export/", "discussion-statistics.csv"); } catch (failure) { setError((failure as Error).message); } }}>Export CSV</button>}{stats ? <><div className="db-stat-grid">{(["posts", "questions", "notes", "polls", "answers", "followups", "views"] as const).map(key => <article key={key}><strong>{stats[key] ?? 0}</strong><span>{key}</span></article>)}</div>{staff && <section><h2>Participation</h2><div className="db-participants">{(stats.contributors || []).map((row: any, index: number) => <div key={index}><span>{[row.user__first_name, row.user__last_name].filter(Boolean).join(" ") || row.user__username} <small>{row.role}</small></span><span>{row.posts} posts · {row.followups} followups</span></div>)}</div></section>}</> : <p>Loading activity…</p>}</main>}
    {answerKind && detail && <div className="db-modal-backdrop" role="presentation"><form className="db-answer-dialog" role="dialog" aria-modal="true" aria-label={`Edit ${answerKind} answer`} onSubmit={submitAnswer}><h2>{answerKind === "student" ? "Students’ answer" : "Instructors’ answer"}</h2><p>This shared answer can be improved as the discussion develops.</p><textarea autoFocus rows={10} maxLength={10000} required value={answerBody} onChange={event => setAnswerBody(event.target.value)} /><div><button type="button" onClick={() => setAnswerKind(null)}>Cancel</button><button className="db-primary" disabled={busy || !answerBody.trim()}>Save answer</button></div></form></div>}
  </div>;
}
