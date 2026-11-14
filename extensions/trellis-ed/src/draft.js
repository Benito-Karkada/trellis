import { bodyFor } from "./common.js";
const api = globalThis.browser || chrome,
  params = new URLSearchParams(location.search);
const $ = (id) => document.getElementById(id);
let draft;
async function send(type, extra = {}) {
  const result = await api.runtime.sendMessage({
    type,
    id: params.get("id"),
    ...extra,
  });
  if (!result.ok) throw Error(result.error);
  return result.value;
}
function error(message) {
  $("error").hidden = false;
  $("error").textContent = message;
}
function renderCapture(d) {
  $("screenshot").src = d.image;
  $("capture-note").textContent = d.context.clipped
    ? "Part of the exercise is outside the screenshot. You can also include the full instructions as text."
    : "Screenshot of the visible exercise area.";
}
async function initialize() {
  try {
    if (params.has("error")) throw Error(params.get("error"));
    // Background may still be recording the newly created preview tab ID.
    draft = await send("GET_DRAFT");
    $("title").value = draft.title;
    $("assignment").textContent =
      `${draft.context.assignment} · ${draft.context.title}`;
    $("context").textContent = draft.context.instructions;
    renderCapture(draft);
    $("draft").hidden = false;
  } catch (e) {
    error(e.message);
  } finally {
    $("loading").hidden = true;
  }
}
$("discard").onclick = async () => {
  if (draft) await send("DELETE_DRAFT");
  window.close();
};
$("recapture").onclick = async () => {
  $("recapture").disabled = true;
  $("error").hidden = true;
  try {
    draft = await send("RECAPTURE", {
      mode: $("include-code").checked ? "workspace" : "instructions",
    });
    renderCapture(draft);
  } catch (e) {
    error(e.message);
  } finally {
    $("recapture").disabled = false;
  }
};
$("include-code").onchange = () => {
  $("status").textContent =
    "Select Capture again to update the screenshot with this choice.";
};
$("draft").onsubmit = async (e) => {
  e.preventDefault();
  $("continue").disabled = true;
  $("error").hidden = true;
  try {
    if (
      $("include-image").checked &&
      $("include-code").checked !== (draft.context.mode === "workspace")
    )
      throw Error(
        "Capture again to apply your code-workspace choice before continuing.",
      );
    await send("OPEN_ED", {
      title: $("title").value.trim(),
      body: bodyFor(
        draft.context,
        $("question").value,
        $("include-text").checked,
      ),
      includeImage: $("include-image").checked,
    });
    $("status").textContent =
      "Ed is open. Select Fill draft in the Trellis assistant, review it, then click Post in Ed.";
  } catch (e) {
    error(e.message);
  } finally {
    $("continue").disabled = false;
  }
};
initialize();
