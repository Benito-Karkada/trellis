import test from "node:test";
import assert from "node:assert/strict";
import { journeyPosition, journeyUnits, TRAIL } from "./journeyProgress.ts";

test("uses the outline totals and completed work, excluding quizzes and the final problem set", () => {
  const units = journeyUnits([
    { title: "Chapter 1.1", metadata: { activity_count: 20, completed_count: 5 }, activities: [] },
    { title: "Chapter 1.2", activities: [{ status: "completed" }, { status: "viewed" }] },
    { title: "Programming Quiz 1", metadata: { kind: "programming_quiz", unit_number: 1, activity_count: 5, completed_count: 5 }, activities: [] },
    { title: "Final Problem Set", metadata: { activity_count: 10, completed_count: 10 }, activities: [] },
  ]);
  assert.deepEqual(units[0], { number: 1, total: 22, completed: 6 });
  assert.equal(units.reduce((sum, unit) => sum + unit.total, 0), 22);
});

test("new students start at the trailhead and completed units reach their own boards", () => {
  const units = [1, 2, 3, 4, 5].map(number => ({ number, completed: 0, total: 10 }));
  assert.equal(journeyPosition(units).x, TRAIL[0].x);
  units[0].completed = 10;
  assert.equal(journeyPosition(units).x, TRAIL[1].x);
  assert.equal(journeyPosition(units).y, TRAIL[1].y);
  units.forEach(unit => { unit.completed = 10; });
  const summit = journeyPosition(units);
  assert.equal(summit.finished, true);
  assert.equal(summit.x, TRAIL[5].x);
  assert.equal(summit.y, TRAIL[5].y);
});

test("interpolates between every unit board and alternates duck direction", () => {
  const expected = ["right", "left", "right", "left"];
  for (let segment = 1; segment <= 4; segment++) {
    const units = [1, 2, 3, 4, 5].map((number, i) => ({ number, total: 10, completed: i < segment ? 10 : i === segment ? 5 : 0 }));
    const duck = journeyPosition(units);
    assert.equal(duck.facing, expected[segment - 1]);
    assert.equal(duck.x, (TRAIL[segment].x + TRAIL[segment + 1].x) / 2);
    assert.equal(duck.y, (TRAIL[segment].y + TRAIL[segment + 1].y) / 2);
  }
});

test("working ahead doesn't skip unfinished units, and empty or invalid counts never imply completion", () => {
  const units = journeyUnits([
    { title: "Chapter 1", metadata: { activity_count: 0, completed_count: 3 }, activities: [] },
    { title: "Chapter 2", metadata: { activity_count: 10, completed_count: 20 }, activities: [] },
    { title: "Chapter 3", metadata: { activity_count: 10, completed_count: NaN }, activities: [] },
  ]);
  assert.equal(journeyPosition(units).segment, 0);
  assert.equal(journeyPosition(units).finished, false);
  assert.equal(units[1].completed, 10);
  assert.equal(units[2].completed, 0);
});
