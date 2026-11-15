import { useId } from "react";
import { journeyPosition, journeyUnits, TRAIL } from "./journeyProgress";
import type { JourneyLesson } from "./journeyProgress";

export default function MountainJourney({ lessons, mountain }: {
  lessons: JourneyLesson[];
  mountain: boolean;
}) {
  const titleId = useId(), descriptionId = useId();
  const units = journeyUnits(lessons);
  const position = journeyPosition(units);
  const current = units[position.segment];
  const completedUnits = units.filter((unit) => unit.total > 0 && unit.completed >= unit.total).length;
  const passed = [...TRAIL.slice(0, position.segment + 1), { x: position.x, y: position.y }];
  const toPoints = (points: { x: number; y: number }[]) => points.map(({ x, y }) => `${x},${y}`).join(" ");
  // The five-board artwork represents the CS 1301 proof of concept. Other
  // courses get their own actual section progress, rather than invented units.
  if (!mountain) {
    return <section className="ch-journey ch-journey-sections" aria-label="Course journey">
      <h3>Your course journey</h3>
      <p>Track your progress through each section.</p>
      {lessons.length ? <ul>{lessons.map((lesson, index) => {
        const total = lesson.metadata?.activity_count ?? lesson.activities.length;
        const done = lesson.metadata?.completed_count ?? lesson.activities.filter((part) => part.status === "completed").length;
        return <li key={index}><strong>{lesson.title}</strong><span>{done} / {total} parts</span>
          <progress aria-label={`${lesson.title} progress`} value={done} max={total || 1} /></li>;
      })}</ul> : <p>Your journey begins when your instructor adds content.</p>}
    </section>;
  }
  const description = position.finished
    ? "All five units completed. Your duck has reached the summit."
    : `Working toward Unit ${current.number}: ${current.completed} of ${current.total} parts completed. Your duck moves as you complete each part, not as deadlines pass.`;
  return <section className="ch-journey" aria-labelledby={titleId}>
    <header className="ch-journey-heading">
      <div><h3 id={titleId}>Your course journey</h3><p>Every completed part is a step up.</p></div>
      <span>{completedUnits} / 5 units</span>
    </header>
    <div className="ch-journey-picture">
      <svg className="ch-journey-art" viewBox="0 0 1132 1556" role="img" aria-labelledby={`${titleId} ${descriptionId}`}>
        <desc id={descriptionId}>{description}</desc>
        <image href="/journey/mountain.png" width="1132" height="1556" />
        <polyline className="ch-journey-trail" points={toPoints(TRAIL)} />
        <polyline className="ch-journey-trail ch-journey-trail-done" points={toPoints(passed)} />
        <g className="ch-journey-duck" data-facing={position.facing} style={{ transform: `translate(${position.x}px, ${position.y}px)` }}>
          <g className="ch-journey-duck-bob">
            <ellipse cx="0" cy="-4" rx="82" ry="13" fill="#151a20" opacity=".2" />
            <g transform={position.facing === "right" ? "scale(-1 1)" : undefined}>
              <image href="/journey/hiking-duck.png" x="-130" y="-189" width="260" height="189" />
            </g>
          </g>
        </g>
      </svg>
    </div>
    <footer className="ch-journey-caption" aria-live="polite">
      <strong>{position.finished ? "Summit reached!" : `Working toward Unit ${current.number}`}</strong>
      <span>{position.finished ? "All five units complete" : `${current.completed} / ${current.total} parts complete`}</span>
      <small>Based on completed coursework, not due dates.</small>
    </footer>
  </section>;
}
