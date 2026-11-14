// This function is serialized by scripting.executeScript into Ed's MAIN world.
// Keep every dependency inside it. No private Ed APIs or framework state are used.
export async function fillOnEdPage(draft, doc = document, operation = "fill") {
  // DOM-only adapter. No private Ed APIs, React internals, or automatic posting.
  function editorControls(doc = document) {
    const visible = (el) =>
      !el.hidden &&
      el.getAttribute("aria-hidden") !== "true" &&
      el.getClientRects().length > 0;
    let title = doc.querySelector('input[aria-label="Title"]');
    if (!title) {
      const label = [...doc.querySelectorAll("label")].find(
        (el) => el.textContent.trim() === "Title",
      );
      title =
        label?.control ||
        (label?.getAttribute("for")
          ? doc.getElementById(label.getAttribute("for"))
          : label?.querySelector("input"));
    }
    if (!title)
      title = [...doc.querySelectorAll("input")].find(
        (el) =>
          visible(el) && (el.placeholder === "Title" || el.name === "title"),
      );
    const candidates = [
      ...doc.querySelectorAll(
        '[contenteditable="true"][aria-label="Thread editor"], [role="textbox"][aria-label="Thread editor"], .ProseMirror[contenteditable="true"]',
      ),
    ].filter(visible);
    const body =
      candidates.find(
        (el) => el.getAttribute("aria-label") === "Thread editor",
      ) || (candidates.length === 1 ? candidates[0] : null);
    return { title, body };
  }
  function normalize(value) {
    return value.replace(/\s+/g, " ").trim();
  }
  async function fillDraft(draft, doc) {
    const { title, body } = editorControls(doc);
    if (!title || !body)
      throw Error(
        "Ed’s title or thread editor is not ready. Select a category, then try again.",
      );
    const existing = normalize(body.innerText || body.textContent || "");
    if (
      (title.value.trim() && title.value !== draft.title) ||
      (existing && existing !== normalize(draft.body))
    )
      throw Error(
        "Ed already contains text. Use a new empty thread so your existing work is not overwritten.",
      );
    const questionType = [
      ...doc.querySelectorAll('[role="radio"], label'),
    ].find((el) => el.textContent.trim() === "Question");
    questionType?.click();
    if (title.value !== draft.title) {
      const setter = Object.getOwnPropertyDescriptor(
        doc.defaultView.HTMLInputElement.prototype,
        "value",
      ).set;
      setter.call(title, draft.title);
      title.dispatchEvent(
        new doc.defaultView.Event("input", { bubbles: true }),
      );
      title.dispatchEvent(
        new doc.defaultView.Event("change", { bubbles: true }),
      );
    }
    if (existing !== normalize(draft.body)) {
      body.focus();
      await new Promise((resolve) => setTimeout(resolve, 100));
      const range = doc.createRange();
      range.selectNodeContents(body);
      const selection = doc.defaultView.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      const wrapper = doc.createElement("div");
      for (const line of draft.body.split("\n")) {
        const paragraph = doc.createElement("p");
        if (line) paragraph.textContent = line;
        else paragraph.append(doc.createElement("br"));
        wrapper.append(paragraph);
      }
      const transfer = new doc.defaultView.DataTransfer();
      transfer.setData("text/html", wrapper.innerHTML);
      body.dispatchEvent(
        new doc.defaultView.ClipboardEvent("paste", {
          bubbles: true,
          cancelable: true,
          clipboardData: transfer,
        }),
      );
      await new Promise((resolve) => setTimeout(resolve, 200));
      if (!normalize(body.innerText || body.textContent || "")) {
        if (!doc.execCommand("insertHTML", false, wrapper.innerHTML))
          throw Error(
            "Ed did not accept the body. Your draft is still available in the extension.",
          );
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
    if (
      title.value !== draft.title ||
      normalize(body.innerText || body.textContent || "") !==
        normalize(draft.body)
    )
      throw Error(
        "Ed did not retain the draft. Keep the preview open and try again.",
      );
    return body;
  }
  function pngFile(data, win = window) {
    const bytes = win.atob(data.split(",")[1]);
    return new win.File(
      [Uint8Array.from(bytes, (c) => c.charCodeAt(0))],
      "trellis-exercise.png",
      { type: "image/png" },
    );
  }
  async function attachScreenshot(body, image, doc = document) {
    const win = doc.defaultView;
    const before = new Set([...body.querySelectorAll("img")]);
    const file = pngFile(image, win);
    const transfer = new win.DataTransfer();
    transfer.items.add(file);
    // Ed’s editor handles pasted images using its own upload path/session.
    body.focus();
    const range = doc.createRange();
    range.selectNodeContents(body);
    range.collapse(false);
    const selection = win.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    body.dispatchEvent(
      new win.ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: transfer,
      }),
    );
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const inserted = [...body.querySelectorAll("img")].find(
        (img) =>
          !before.has(img) &&
          /^https:\/\//.test(img.getAttribute("src") || "") &&
          img.complete &&
          img.naturalWidth > 0,
      );
      if (inserted) return true;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    return false;
  }

  try {
    if (operation === "controls") return editorControls(doc);
    if (operation === "png") return pngFile(draft.image, doc.defaultView);
    const body = await fillDraft(draft, doc);
    const attached = draft.image
      ? await attachScreenshot(body, draft.image, doc)
      : null;
    return { filled: true, attached };
  } catch (error) {
    return { filled: false, error: error.message };
  }
}
export async function editorControls(doc) {
  return fillOnEdPage(null, doc, "controls");
}
export async function fillDraft(draft, doc) {
  const result = await fillOnEdPage({ ...draft, image: null }, doc);
  if (!result.filled) throw Error(result.error);
  return result;
}
export async function pngFile(data, win = window) {
  return fillOnEdPage({ image: data }, { defaultView: win }, "png");
}
