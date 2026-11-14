import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { parseHTML } from "linkedom";
import {
  LIVE_ORIGIN,
  TTL,
  edCourse,
  isTrellisUrl,
  isNewThread,
  validContext,
  validDraft,
  bodyFor,
  cropRect,
} from "../src/common.js";
import { collectContext } from "../src/source.js";
import { editorControls, fillDraft, pngFile } from "../src/ed-page.js";
const context = () => ({
  allowed: true,
  kind: "lesson",
  url: LIVE_ORIGIN + "/#/course?lesson=2&activity=4",
  edUrl: "https://edstem.org/us/courses/100193/discussion",
  title: "Variables",
  assignment: "Chapter 2.2",
  activityId: 4,
  lessonId: 2,
  instructions: "Print the sum.\n\nprint(2 + 3)",
});
const draft = () => ({
  id: "fixture",
  sourceTabId: 1,
  createdAt: Date.now(),
  context: context(),
  title: "Question about Variables",
  body: "Why does this print 5?",
});
test("only configured Trellis host and local development are allowed", () => {
  assert.ok(isTrellisUrl(LIVE_ORIGIN + "/#/course"));
  assert.ok(isTrellisUrl("http://localhost:8765/"));
  for (const u of [
    "https://evil.example",
    "https://" + new URL(LIVE_ORIGIN).hostname + ".evil.example/",
    "file:///etc/passwd",
    "https://localhost/",
  ])
    assert.equal(isTrellisUrl(u), false);
});
test("Ed destination rejects credentials, extra origins, query strings and incorrect paths", () => {
  assert.equal(edCourse(context().edUrl + "/"), context().edUrl);
  for (const u of [
    "http://edstem.org/us/courses/1/discussion",
    "https://edstem.org.evil/us/courses/1/discussion",
    "https://a@edstem.org/us/courses/1/discussion",
    "https://edstem.org/us/courses/1/discussion?title=x",
    "https://edstem.org/us/courses/1/discussion/new",
  ])
    assert.throws(() => edCourse(u));
  assert.ok(isNewThread(context().edUrl + "/new", context().edUrl));
  assert.equal(
    isNewThread(
      "https://edstem.org/us/courses/2/discussion/new",
      context().edUrl,
    ),
    false,
  );
});
test("quiz, Config and stale/oversized drafts are rejected", () => {
  assert.equal(validContext(context()).title, "Variables");
  assert.throws(() => validContext({ ...context(), kind: "programming_quiz" }));
  assert.throws(() => validContext({ ...context(), allowed: false }));
  assert.throws(() =>
    validDraft({ ...draft(), createdAt: Date.now() - TTL - 1 }),
  );
  assert.throws(() =>
    validDraft({ ...draft(), createdAt: Date.now() + 10000 }),
  );
  assert.throws(() =>
    validDraft({ ...draft(), image: "https://external/image.png" }),
  );
  assert.throws(() => validDraft({ ...draft(), title: "x".repeat(501) }));
});
test("post context retains code indentation and student question without interpreting HTML", () => {
  const body = bodyFor(context(), "Why? <script>alert(1)</script>", true);
  assert.ok(body.startsWith("Why? <script>"));
  assert.ok(body.includes("print(2 + 3)"));
  assert.ok(body.includes("Assignment: Chapter 2.2"));
  assert.ok(!body.includes("http"));
});
test("screenshot crop is clipped to visible exercise and excludes surrounding UI", () => {
  assert.deepEqual(
    cropRect(
      { x: 200, y: -50, width: 600, height: 900 },
      { width: 1000, height: 700 },
    ),
    { x: 200, y: 0, width: 600, height: 700 },
  );
  assert.throws(() =>
    cropRect(
      { x: 1000, y: 0, width: 600, height: 400 },
      { width: 1000, height: 700 },
    ),
  );
});
function sourceFixture(allowed = "true", kind = "lesson") {
  const { document } = parseHTML(
    `<html><body><div data-trellis-ed-version="1" data-allowed="${allowed}" data-kind="${kind}" data-title="Variables" data-assignment="Chapter 2.2" data-activity="4" data-lesson="2" data-ed-url="${context().edUrl}" data-url="${context().url}"><section data-trellis-ed-instructions><p>Print the sum.</p><pre>if True:\n    print(2 + 3)</pre><fieldset><legend>What prints?</legend><label><input value="student secret">Five</label><div class="question-hints">Correct answer secret</div></fieldset><button>Submit</button><textarea>private input</textarea><div class="native-submit">Reset exercise</div></section></div></body></html>`,
  );
  const area = document.querySelector("section");
  area.getBoundingClientRect = () => ({
    x: 250,
    y: 100,
    width: 600,
    height: 450,
    top: 100,
    left: 250,
    bottom: 550,
    right: 850,
  });
  return document;
}
test("source extracts question/code and choices without hints or typed answers", () => {
  const old = globalThis.document;
  globalThis.document = sourceFixture();
  globalThis.innerWidth = 1200;
  globalThis.innerHeight = 800;
  try {
    const c = collectContext();
    assert.ok(c.instructions.includes("    print(2 + 3)"));
    assert.ok(c.instructions.includes("What prints?"));
    assert.ok(c.instructions.includes("Five"));
    for (const s of [
      "student secret",
      "Correct answer secret",
      "private input",
      "Submit",
      "Reset exercise",
    ])
      assert.ok(!c.instructions.includes(s), s);
  } finally {
    globalThis.document = old;
  }
});
test("source fails closed for quiz and disallowed context", () => {
  const old = globalThis.document;
  try {
    globalThis.document = sourceFixture("true", "programming_quiz");
    assert.throws(() => collectContext());
    globalThis.document = sourceFixture("false");
    assert.throws(() => collectContext());
  } finally {
    globalThis.document = old;
  }
});
function edFixture(existing = "") {
  const { document, window } = parseHTML(
    `<html><body><label for="t">Title</label><input id="t"><div contenteditable="true" aria-label="Thread editor">${existing}</div><button>Post</button></body></html>`,
  );
  window.HTMLElement.prototype.getClientRects = function () {
    return [{}];
  };
  return { document, window };
}
test("Ed adapter locates labeled fields and refuses to overwrite another draft", async () => {
  const { document } = edFixture("My existing work");
  const controls = await editorControls(document);
  assert.equal(controls.title.id, "t");
  assert.equal(controls.body.getAttribute("aria-label"), "Thread editor");
  await assert.rejects(
    () => fillDraft(draft(), document),
    /already contains text/,
  );
  assert.equal(controls.body.textContent, "My existing work");
});
test("image fallback creates a PNG file without using an Ed API token", async () => {
  class File {
    constructor(parts, name, opts) {
      Object.assign(this, { parts, name, type: opts.type });
    }
  }
  const file = await pngFile("data:image/png;base64,YWJj", {
    atob: (s) => Buffer.from(s, "base64").toString("binary"),
    File,
  });
  assert.equal(file.name, "trellis-exercise.png");
  assert.equal(file.type, "image/png");
  assert.equal(file.parts[0].length, 3);
});
test("content script has no Post action and package permissions are narrowly scoped", async () => {
  const content = await readFile(
    new URL("../src/ed-content.js", import.meta.url),
    "utf8",
  );
  assert.ok(!/\.submit\(|requestSubmit|fetch\(/.test(content));
  const manifest = JSON.parse(
    await readFile(
      new URL("../dist/chromium/manifest.json", import.meta.url),
      "utf8",
    ),
  );
  assert.deepEqual(manifest.host_permissions, ["https://edstem.org/*"]);
  for (const permission of [
    "cookies",
    "debugger",
    "webRequest",
    "tabs",
    "<all_urls>",
  ])
    assert.ok(!manifest.permissions.includes(permission));
});

test("the serialized MAIN-world function fills paragraphs and confirms an uploaded image", async () => {
  const { fillOnEdPage } = await import("../src/ed-page.js");
  const { document, window } = edFixture();
  class Transfer {
    constructor() {
      this.data = {};
      this.files = [];
      this.items = { add: (file) => this.files.push(file) };
    }
    setData(type, value) {
      this.data[type] = value;
    }
    getData(type) {
      return this.data[type] || "";
    }
  }
  class PasteEvent extends window.Event {
    constructor(type, opts) {
      super(type, opts);
      this.clipboardData = opts.clipboardData;
    }
  }
  window.DataTransfer = Transfer;
  window.ClipboardEvent = PasteEvent;
  window.atob = (s) => Buffer.from(s, "base64").toString("binary");
  window.File = globalThis.File;
  window.getSelection = () => ({ removeAllRanges() {}, addRange() {} });
  document.createRange = () => ({ selectNodeContents() {}, collapse() {} });
  const editor = document.querySelector("[contenteditable]");
  editor.focus = () => {};
  editor.addEventListener("paste", (event) => {
    if (event.clipboardData.files.length) {
      const img = document.createElement("img");
      img.src = "https://edstem.org/synthetic-upload.png";
      Object.defineProperties(img, {
        complete: { value: true },
        naturalWidth: { value: 200 },
      });
      editor.append(img);
    } else editor.innerHTML = event.clipboardData.getData("text/html");
  });
  // Compile the exact serialized function without access to its module's helpers.
  const vm = await import("node:vm");
  const injected = vm.runInNewContext("(" + fillOnEdPage.toString() + ")", {
    setTimeout,
    Date,
    Uint8Array,
  });
  const result = await injected(
    {
      ...draft(),
      body: "Paragraph one.\n\n# Python comment\n    print(5)",
      image: "data:image/png;base64,YWJj",
    },
    document,
  );
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    filled: true,
    attached: true,
  });
  assert.equal(
    document.querySelector("input").value,
    "Question about Variables",
  );
  assert.ok(editor.textContent.includes("# Python comment"));
  assert.ok(editor.querySelector("img"));
});

test("default post stays compact, with no Trellis link or duplicated instructions", () => {
  const body = bodyFor(context(), "Why does this happen?");
  assert.ok(body.includes("Exercise: Variables"));
  assert.ok(!body.includes("Print the sum."));
  assert.ok(!body.includes("http"));
});
