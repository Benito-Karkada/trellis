import {
  isTrellisUrl,
  validContext,
  validDraft,
  bodyFor,
  cropRect,
  isNewThread,
  TTL,
} from "./common.js";
import { collectContext, cropScreenshot } from "./source.js";
import { fillOnEdPage } from "./ed-page.js";
const api = globalThis.browser || chrome;
const key = (id) => `draft:${id}`;
const page = (name) => api.runtime.getURL(name);
const isExtensionPage = (sender) => {
  try {
    return (
      new URL(sender.url).protocol === new URL(page("draft.html")).protocol &&
      new URL(sender.url).host === new URL(page("draft.html")).host &&
      new URL(sender.url).pathname === new URL(page("draft.html")).pathname
    );
  } catch {
    return false;
  }
};
async function get(id) {
  const data = await api.storage.local.get(key(id));
  return validDraft(data[key(id)]);
}
async function save(d) {
  validDraft(d);
  await api.storage.local.set({ [key(d.id)]: d });
}
async function prune() {
  const all = await api.storage.local.get(null);
  const expired = Object.entries(all)
    .filter(
      ([k, d]) =>
        k.startsWith("draft:") &&
        (!d.createdAt || Date.now() - d.createdAt > TTL),
    )
    .map(([k]) => k);
  if (expired.length) await api.storage.local.remove(expired);
}
async function capture(tabId, mode, expected) {
  const tab = await api.tabs.get(tabId);
  if (!isTrellisUrl(tab.url))
    throw Error("Open Trellis first, then click the extension.");
  if (!tab.active)
    throw Error("Keep the Trellis exercise tab selected while capturing.");
  const [{ result: c }] = await api.scripting.executeScript({
    target: { tabId },
    func: collectContext,
    args: [mode],
  });
  validContext(c);
  if (
    expected &&
    (c.url !== expected.url || c.activityId !== expected.activityId)
  )
    throw Error("The exercise changed. Start a new draft.");
  const active = (
    await api.tabs.query({ active: true, windowId: tab.windowId })
  )[0];
  if (active?.id !== tabId)
    throw Error("The selected tab changed. Capture the exercise again.");
  const image = await api.tabs.captureVisibleTab(tab.windowId, {
    format: "png",
  });
  const [{ result: checked }] = await api.scripting.executeScript({
    target: { tabId },
    func: collectContext,
    args: [mode],
  });
  if (
    checked.url !== c.url ||
    JSON.stringify(checked.rect) !== JSON.stringify(c.rect)
  )
    throw Error("The page moved during capture. Try again.");
  const [{ result: cropped }] = await api.scripting.executeScript({
    target: { tabId },
    func: cropScreenshot,
    args: [image, cropRect(c.rect, c.viewport), c.viewport],
  });
  return { context: c, image: cropped };
}
api.action.onClicked.addListener(async (tab) => {
  await prune();
  const id = crypto.randomUUID();
  try {
    const captured = await capture(tab.id, "instructions");
    const d = {
      id,
      sourceTabId: tab.id,
      createdAt: Date.now(),
      ...captured,
      title: `Question about ${captured.context.title}`.slice(0, 500),
      body: bodyFor(captured.context, "My question:"),
    };
    // Keep at most two screenshots to stay below extension storage quotas.
    const all = await api.storage.local.get(null);
    const old = Object.values(all)
      .filter((d) => d?.id && d?.createdAt)
      .sort((a, b) => b.createdAt - a.createdAt)
      .slice(1);
    if (old.length) await api.storage.local.remove(old.map((d) => key(d.id)));
    await save(d);
    const opened = await api.tabs.create({ url: page(`draft.html?id=${id}`) });
    d.previewTabId = opened.id;
    await save(d);
  } catch (error) {
    await api.tabs.create({
      url: page(`draft.html?error=${encodeURIComponent(error.message)}`),
    });
  }
});
export async function handle(message, sender) {
  if (!message || typeof message.type !== "string")
    throw Error("Invalid request.");
  await prune();
  if (message.type === "ED_READY") {
    if (!sender.tab?.id) throw Error("No Ed tab.");
    const all = await api.storage.local.get(null);
    const d = Object.values(all).find((d) => d?.targetTabId === sender.tab.id);
    if (!d || !isNewThread(sender.url, d.context.edUrl)) return null;
    validDraft(d);
    return {
      id: d.id,
      title: d.title,
      body: d.body,
      image: d.image,
      createdAt: d.createdAt,
    };
  }
  if (message.type === "FILL_ED") {
    const all = await api.storage.local.get(null);
    const d = Object.values(all).find((d) => d?.targetTabId === sender.tab?.id);
    if (!d || !isNewThread(sender.url, d.context.edUrl))
      throw Error("No reviewed draft belongs to this Ed tab.");
    validDraft(d);
    const [{ result }] = await api.scripting.executeScript({
      target: { tabId: sender.tab.id },
      world: "MAIN",
      func: fillOnEdPage,
      args: [{ title: d.title, body: d.body, image: d.image }],
    });
    return result;
  }
  if (!isExtensionPage(sender))
    throw Error("Only the extension preview can send this request.");
  const d = await get(message.id);
  if (d.previewTabId && sender.tab?.id !== d.previewTabId)
    throw Error("This draft belongs to another preview tab.");
  if (message.type === "GET_DRAFT") return d;
  if (message.type === "DELETE_DRAFT") {
    await api.storage.local.remove(key(d.id));
    return true;
  }
  if (message.type === "RECAPTURE") {
    await api.tabs.update(d.sourceTabId, { active: true });
    try {
      const captured = await capture(
        d.sourceTabId,
        message.mode === "workspace" ? "workspace" : "instructions",
        d.context,
      );
      Object.assign(d, captured);
      await save(d);
      return d;
    } finally {
      if (sender.tab?.id)
        await api.tabs.update(sender.tab.id, { active: true });
    }
  }
  if (message.type === "OPEN_ED") {
    Object.assign(d, {
      title: message.title,
      body: message.body,
      image: message.includeImage ? d.image : null,
    });
    validDraft(d);
    // Bind before navigation so the content script cannot win a creation race.
    const target = await api.tabs.create({ url: "about:blank", active: true });
    d.targetTabId = target.id;
    await save(d);
    await api.tabs.update(target.id, { url: d.context.edUrl + "/new" });
    return true;
  }
  throw Error("Unknown request.");
}
api.runtime.onMessage.addListener((message, sender, respond) => {
  handle(message, sender)
    .then((value) => respond({ ok: true, value }))
    .catch((error) => respond({ ok: false, error: error.message }));
  return true;
});
// No cookie access, network interception, Ed API token, or telemetry.
api.storage.local
  .setAccessLevel?.({ accessLevel: "TRUSTED_CONTEXTS" })
  .catch(() => {});
