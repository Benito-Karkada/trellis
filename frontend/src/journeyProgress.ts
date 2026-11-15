export type JourneyLesson = {
  title: string;
  metadata?: {
    kind?: string;
    unit_number?: number;
    activity_count?: number;
    completed_count?: number;
  };
  activities: { status: string }[];
};

export type JourneyUnit = { number: number; completed: number; total: number };

// Anchors are in the supplied mountain artwork's 1132 × 1556 coordinate space.
// The trailhead lets completing Unit 1 reach its board, rather than Unit 2.
export const TRAIL = [
  { x: 220, y: 1430 },
  { x: 245, y: 1250 },
  { x: 880, y: 1000 },
  { x: 340, y: 780 },
  { x: 700, y: 610 },
  { x: 530, y: 390 },
];

function count(value: number) {
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

export function journeyUnits(lessons: JourneyLesson[]): JourneyUnit[] {
  return [1, 2, 3, 4, 5].map((number) => {
    let total = 0, completed = 0;
    for (const lesson of lessons) {
      if (lesson.metadata?.kind === "programming_quiz") continue;
      const unit = lesson.metadata?.unit_number
        ?? Number(lesson.title.match(/(?:Chapter|Unit)\s+(\d+)/i)?.[1]);
      if (unit !== number) continue;
      const parts = count(lesson.metadata?.activity_count ?? lesson.activities.length);
      total += parts;
      completed += Math.min(parts, count(lesson.metadata?.completed_count
        ?? lesson.activities.filter((part) => part.status === "completed").length));
    }
    return { number, completed, total };
  });
}

export function journeyPosition(units: JourneyUnit[]) {
  // Keep the duck on the first unfinished unit; working ahead is still recorded
  // in each unit's progress, but doesn't imply an earlier unit is finished.
  const firstUnfinished = units.findIndex((unit) => unit.total === 0 || unit.completed < unit.total);
  const finished = firstUnfinished < 0;
  const segment = finished ? 4 : Math.min(firstUnfinished, 4);
  const current = units[segment];
  const fraction = finished ? 1 : current?.total
    ? Math.max(0, Math.min(1, current.completed / current.total)) : 0;
  const from = TRAIL[segment], to = TRAIL[segment + 1];
  return {
    segment, fraction, finished,
    x: from.x + (to.x - from.x) * fraction,
    y: from.y + (to.y - from.y) * fraction,
    facing: to.x >= from.x ? "right" as const : "left" as const,
  };
}
