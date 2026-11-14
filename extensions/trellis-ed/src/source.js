// Both functions are serialized by scripting.executeScript; keep them self-contained.
export function collectContext(mode = "instructions") {
  const bridge = document.querySelector('[data-trellis-ed-version="1"]');
  if (
    !bridge ||
    bridge.dataset.allowed !== "true" ||
    bridge.dataset.kind === "programming_quiz"
  )
    throw Error(
      "Open a regular exercise or sandbox in Learn view. Quizzes and Config view cannot be shared.",
    );
  const instructions = document.querySelector("[data-trellis-ed-instructions]");
  const area =
    mode === "workspace"
      ? document.querySelector("[data-trellis-ed-workspace]")
      : instructions;
  if (!instructions || !area) throw Error("The exercise is still loading.");
  const clone = instructions.cloneNode(true);
  for (const choice of clone.querySelectorAll("button.choice-review")) {
    const text = document.createElement("p");
    text.textContent =
      choice.querySelector("span")?.textContent || choice.textContent;
    choice.replaceWith(text);
  }
  clone
    .querySelectorAll(
      'input,textarea,select,button,.native-submit,.question-hints,.choice-review-note,.feedback,.tip,[role="alert"],[data-ed-exclude],iframe,video',
    )
    .forEach((el) => el.remove());
  // Copy question text and code blocks, never students’ form values or feedback.
  const lines = [];
  function walk(node) {
    if (node.nodeType === 3) {
      lines.push(node.textContent);
      return;
    }
    if (node.nodeType !== 1) return;
    const block = /^(P|DIV|PRE|LI|LEGEND|FIELDSET|H[1-6]|BR)$/.test(
      node.tagName,
    );
    if (block) lines.push("\n");
    if (node.tagName === "IMG")
      lines.push(
        node.alt
          ? `[Image: ${node.alt}]`
          : "[See exercise screenshot for image]",
      );
    for (const child of node.childNodes) walk(child);
    if (block) lines.push("\n");
  }
  walk(clone);
  const box = area.getBoundingClientRect();
  return {
    allowed: true,
    kind: bridge.dataset.kind,
    title: bridge.dataset.title,
    assignment: bridge.dataset.assignment,
    activityId: bridge.dataset.activity,
    lessonId: bridge.dataset.lesson,
    edUrl: bridge.dataset.edUrl,
    url: bridge.dataset.url,
    instructions: lines
      .join("")
      .replace(/\n[ \t]*\n[ \t]*\n/g, "\n\n")
      .trim(),
    rect: { x: box.x, y: box.y, width: box.width, height: box.height },
    viewport: { width: innerWidth, height: innerHeight },
    mode,
    clipped:
      box.top < 0 ||
      box.left < 0 ||
      box.bottom > innerHeight ||
      box.right > innerWidth,
  };
}
export async function cropScreenshot(image, rect, viewport) {
  const img = new Image();
  img.src = image;
  await img.decode();
  const ratioX = img.naturalWidth / viewport.width,
    ratioY = img.naturalHeight / viewport.height;
  const scale = Math.min(1, 1400 / (rect.width * ratioX));
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(rect.width * ratioX * scale);
  canvas.height = Math.ceil(rect.height * ratioY * scale);
  canvas
    .getContext("2d")
    .drawImage(
      img,
      rect.x * ratioX,
      rect.y * ratioY,
      rect.width * ratioX,
      rect.height * ratioY,
      0,
      0,
      canvas.width,
      canvas.height,
    );
  return canvas.toDataURL("image/png");
}
