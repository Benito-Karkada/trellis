export const LIVE_ORIGIN =
  "https://cs1301-poc-web-v2.agreeablewave-32290e77.southcentralus.azurecontainerapps.io";
export const TTL = 30 * 60 * 1000;
export const MAX_IMAGE = 3 * 1024 * 1024;
export function isTrellisUrl(value) {
  try {
    const u = new URL(value);
    return (
      u.origin === LIVE_ORIGIN ||
      (["localhost", "127.0.0.1"].includes(u.hostname) &&
        u.protocol === "http:")
    );
  } catch {
    return false;
  }
}
export function edCourse(value) {
  const u = new URL(value);
  if (
    u.protocol !== "https:" ||
    u.hostname !== "edstem.org" ||
    u.port ||
    u.username ||
    u.password ||
    u.search ||
    u.hash ||
    !/^\/(us|au|eu|ca)\/courses\/\d+\/discussion\/?$/.test(u.pathname)
  )
    throw Error("Invalid Ed course URL.");
  return u.href.replace(/\/$/, "");
}
export function isNewThread(value, course) {
  try {
    const u = new URL(value);
    return u.origin + u.pathname === edCourse(course) + "/new";
  } catch {
    return false;
  }
}
export function validContext(c) {
  if (
    !c ||
    c.allowed !== true ||
    c.kind === "programming_quiz" ||
    !isTrellisUrl(c.url) ||
    !/^\d+$/.test(String(c.activityId)) ||
    !/^\d+$/.test(String(c.lessonId)) ||
    !c.title?.trim()
  )
    throw Error(
      "Open a regular exercise or sandbox in Trellis. Programming quizzes and Config view are excluded.",
    );
  edCourse(c.edUrl);
  if (
    c.title.length > 1000 ||
    c.assignment.length > 1000 ||
    c.instructions.length > 50000
  )
    throw Error("This exercise is too large to capture.");
  return c;
}
export function validDraft(d, now = Date.now()) {
  if (
    !d ||
    !Number.isFinite(d.createdAt) ||
    now - d.createdAt > TTL ||
    now < d.createdAt ||
    !d.id ||
    !Number.isInteger(d.sourceTabId)
  )
    throw Error("This draft expired. Capture the exercise again.");
  validContext(d.context);
  if (
    typeof d.title !== "string" ||
    !d.title.trim() ||
    d.title.length > 500 ||
    typeof d.body !== "string" ||
    d.body.length > 60000
  )
    throw Error(
      "Use a title under 500 characters and a question under 60,000 characters.",
    );
  if (
    d.image &&
    (!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(d.image) ||
      d.image.length > MAX_IMAGE)
  )
    throw Error("The screenshot is too large.");
  return d;
}
export function bodyFor(c, question, includeInstructions = false) {
  return `${question.trim()}\n\nExercise: ${c.title}\nAssignment: ${c.assignment}${includeInstructions ? `\n\n${c.instructions}` : ""}`;
}
export function cropRect(rect, viewport) {
  const x = Math.max(0, rect.x),
    y = Math.max(0, rect.y);
  const width = Math.min(viewport.width, rect.x + rect.width) - x;
  const height = Math.min(viewport.height, rect.y + rect.height) - y;
  if (width < 24 || height < 24)
    throw Error("Scroll the exercise into view, then capture it again.");
  return { x, y, width, height };
}
