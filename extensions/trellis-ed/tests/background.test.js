import test from "node:test";
import assert from "node:assert/strict";
import { LIVE_ORIGIN } from "../src/common.js";
const rows = {},
  calls = [];
const api = {
  runtime: {
    getURL: (p) => "chrome-extension://fixture/" + p,
    onMessage: { addListener() {} },
  },
  action: { onClicked: { addListener() {} } },
  storage: {
    local: {
      async get(key) {
        return key === null ? { ...rows } : { [key]: rows[key] };
      },
      async set(data) {
        Object.assign(rows, data);
      },
      async remove(keys) {
        for (const k of [].concat(keys)) delete rows[k];
      },
    },
  },
  tabs: {
    async create(opts) {
      calls.push(["create", opts]);
      return { id: 55 };
    },
    async update(id, opts) {
      calls.push(["update", id, opts]);
    },
  },
};
globalThis.browser = api;
const { handle } = await import("../src/background.js");
function seed() {
  for (const k in rows) delete rows[k];
  calls.length = 0;
  rows["draft:test"] = {
    id: "test",
    sourceTabId: 1,
    previewTabId: 9,
    targetTabId: 12,
    createdAt: Date.now(),
    title: "My question",
    body: "Explain this?",
    context: {
      allowed: true,
      kind: "lesson",
      url: LIVE_ORIGIN + "/#/course?lesson=2&activity=4",
      edUrl: "https://edstem.org/us/courses/100193/discussion",
      title: "Exercise",
      assignment: "Lesson",
      activityId: 4,
      lessonId: 2,
      instructions: "Print 5.",
    },
  };
}
const sender = () => ({
  url: "chrome-extension://fixture/draft.html?id=test",
  tab: { id: 9 },
});
test("Ed only receives a draft bound to its exact tab and course", async () => {
  seed();
  assert.equal(
    await handle(
      { type: "ED_READY" },
      {
        url: "https://edstem.org/us/courses/100193/discussion/new",
        tab: { id: 99 },
      },
    ),
    null,
  );
  assert.equal(
    await handle(
      { type: "ED_READY" },
      {
        url: "https://edstem.org/us/courses/9/discussion/new",
        tab: { id: 12 },
      },
    ),
    null,
  );
  const d = await handle(
    { type: "ED_READY" },
    {
      url: "https://edstem.org/us/courses/100193/discussion/new",
      tab: { id: 12 },
    },
  );
  assert.equal(d.title, "My question");
  assert.equal(d.sourceTabId, undefined);
});
test("ordinary webpages and another preview cannot read or replace drafts", async () => {
  seed();
  await assert.rejects(() =>
    handle(
      { type: "GET_DRAFT", id: "test" },
      { url: "https://evil.example", tab: { id: 9 } },
    ),
  );
  await assert.rejects(() =>
    handle({ type: "GET_DRAFT", id: "test" }, { ...sender(), tab: { id: 10 } }),
  );
});
test("reviewed draft is bound before navigating to Ed, with no body in the URL", async () => {
  seed();
  await handle(
    {
      type: "OPEN_ED",
      id: "test",
      title: "Why?",
      body: "My code question",
      includeImage: false,
    },
    sender(),
  );
  assert.equal(rows["draft:test"].targetTabId, 55);
  assert.deepEqual(calls, [
    ["create", { url: "about:blank", active: true }],
    [
      "update",
      55,
      { url: "https://edstem.org/us/courses/100193/discussion/new" },
    ],
  ]);
});
test("expired drafts are pruned and cannot be sent to Ed", async () => {
  seed();
  rows["draft:test"].createdAt = 0;
  await assert.rejects(() => handle({ type: "OPEN_ED", id: "test" }, sender()));
  assert.equal(rows["draft:test"], undefined);
  assert.equal(calls.length, 0);
});
