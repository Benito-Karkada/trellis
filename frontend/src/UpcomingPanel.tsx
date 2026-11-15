import { useEffect, useState } from "react";
import { CalendarDays, Check, Clock3 } from "lucide-react";
import { routeHref } from "./navigation";

export type UpcomingItem = {
  id: number;
  title: string;
  due_at: string;
  earned_points: string;
  maximum_points: string;
  done: boolean;
  full_credit: boolean;
  activity_id: number | null;
  category: string;
  multiple_deadlines: boolean;
};

function urgency(item: UpcomingItem, now: number) {
  const remaining = new Date(item.due_at).getTime() - now;
  if (item.done) return { tone: "done", label: "Checked off" };
  if (remaining < 0) return { tone: "urgent", label: "Overdue" };
  if (remaining <= 86400000) return { tone: "urgent", label: "Due soon" };
  if (remaining <= 3 * 86400000) return { tone: "near", label: "Coming up" };
  return { tone: "later", label: "On the horizon" };
}
const points = (value: string) =>
  Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function UpcomingPanel({
  items = [],
  onToggle,
  onOpen,
  pending = new Set<number>(),
  loading = false,
  error = "",
  onRetry,
  onManageDeadlines,
}: {
  items?: UpcomingItem[];
  onToggle: (id: number, done: boolean) => void;
  onOpen: (lesson: number, activity: number | null) => void;
  pending?: Set<number>;
  loading?: boolean;
  error?: string;
  onRetry: () => void;
  onManageDeadlines?: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(timer);
  }, []);
  return (
    <section className="ch-upcoming" aria-labelledby="upcoming-title">
      <header className="ch-upcoming-heading">
        <div>
          <h3 className="ch-upcoming-title" id="upcoming-title">
            Upcoming
          </h3>
        </div>
        <span className="ch-upcoming-count">
          {items.filter((item) => !item.done).length} to do
        </span>
      </header>
      {error && (
        <div className="ch-upcoming-error" role="alert">
          <span>{error}</span>
          <button onClick={onRetry}>Retry</button>
        </div>
      )}
      {loading && !items.length ? (
        <p className="ch-upcoming-status" role="status">
          Loading deadlines…
        </p>
      ) : !items.length && !error ? (
        <div className="ch-upcoming-empty">
          <CalendarDays size={30} />
          <strong>No deadlines scheduled</strong>
          <p>Assignments will appear here when due dates are set.</p>
          {onManageDeadlines && (
            <button onClick={onManageDeadlines}>Course settings</button>
          )}
        </div>
      ) : (
        <ul className="ch-upcoming-list" role="list">
          {items.map((item) => {
            const date = new Date(item.due_at),
              status = urgency(item, now);
            const fullDate = date.toLocaleString(undefined, {
              dateStyle: "full",
              timeStyle: "short",
            });
            return (
              <li
                key={item.id}
                className={`ch-upcoming-item urgency-${status.tone} ${item.done ? "is-checked" : ""}`}
              >
                <label className="ch-upcoming-checkbox">
                  <input
                    type="checkbox"
                    checked={item.done}
                    disabled={pending.has(item.id)}
                    aria-label={`Mark ${item.title} complete`}
                    onChange={(e) => onToggle(item.id, e.target.checked)}
                  />
                  <span aria-hidden="true">
                    {item.done && <Check size={13} strokeWidth={3} />}
                  </span>
                </label>
                <div className="ch-upcoming-body">
                  <a
                    className="ch-upcoming-name"
                    title={item.title}
                    href={routeHref({
                      page: "course",
                      lessonId: item.id,
                      active: item.activity_id,
                      category: item.category,
                    })}
                    onClick={(e) => {
                      if (
                        !e.metaKey &&
                        !e.ctrlKey &&
                        !e.shiftKey &&
                        !e.altKey
                      ) {
                        e.preventDefault();
                        onOpen(item.id, item.activity_id);
                      }
                    }}
                  >
                    {item.title
                      .replace(/^Chapter\s+/i, "")
                      .replace(/(\d+\.\d+)\s*[-–—]\s*/, "$1 · ")}
                  </a>
                  <span
                    className={`ch-upcoming-points ${item.full_credit ? "full-credit" : ""}`}
                  >
                    {item.full_credit && <Check size={12} />}
                    <b>{points(item.earned_points)}</b> /{" "}
                    {points(item.maximum_points)} pts
                  </span>
                </div>
                <div className="ch-upcoming-deadline">
                  <span className="ch-upcoming-urgency">
                    <Clock3 size={11} />
                    {status.label}
                  </span>
                  <time dateTime={item.due_at} title={fullDate}>
                    <span>
                      {item.multiple_deadlines ? "Next due · " : ""}
                      {date.toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        ...(date.getFullYear() !== new Date(now).getFullYear()
                          ? { year: "numeric" as const }
                          : {}),
                      })}
                    </span>
                    <small>
                      {date.toLocaleTimeString(undefined, {
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </small>
                  </time>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {!!items.length && (
        <p className="ch-upcoming-note">
          Your checklist is personal. Checking a box doesn’t change your grade.
        </p>
      )}
    </section>
  );
}
