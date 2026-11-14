(() => {
  const api = globalThis.browser || chrome;
  let started = false;
  async function start() {
    if (
      started ||
      !/^\/(us|au|eu|ca)\/courses\/\d+\/discussion\/new\/?$/.test(
        location.pathname,
      )
    )
      return;
    const response = await api.runtime
      .sendMessage({ type: "ED_READY" })
      .catch(() => null);
    if (!response?.ok || !response.value) return;
    started = true;
    const draft = response.value;
    const adapter = await import(api.runtime.getURL("ed-page.js"));
    const host = document.createElement("div");
    host.id = "trellis-ed-helper";
    const shadow = host.attachShadow({ mode: "closed" });
    shadow.innerHTML = `<style>:host{all:initial;position:fixed;bottom:20px;right:20px;z-index:2147483647;font:14px/1.5 system-ui;color:#183744}section{width:330px;box-sizing:border-box;padding:20px;border:1px solid #d9d0b5;border-radius:18px;background:#fffdf7;box-shadow:0 12px 40px #102d4333}h2{font-size:18px;margin:0 0 8px}p{margin:8px 0}button,a{font:inherit;border:1px solid #bccbd0;border-radius:9px;padding:9px 12px;background:white;color:#183744;cursor:pointer;display:inline-block;margin:4px 4px 0 0}button.primary{background:#173d3e;color:white;border:0}button:disabled{opacity:.6;cursor:wait}#close{float:right;border:0;margin:0;padding:0 4px;font-size:22px;background:transparent}#status{white-space:pre-wrap}a{font-size:13px}</style><section aria-label="Trellis Ed assistant"><button id="close" aria-label="Close Trellis assistant">×</button><h2>Your Trellis question</h2><p>Fill this empty thread with your reviewed title, question, and exercise image. You choose the category and click Post.</p><button class="primary" id="fill">Fill draft${draft.image ? " & attach image" : ""}</button><p id="status" role="status"></p><div id="fallback" hidden><button id="copy">Copy screenshot</button><a id="download" download="trellis-exercise.png">Download image</a><p>If the image wasn’t attached, paste it into the editor or use Ed’s Insert Image → Upload File.</p></div></section>`;
    document.documentElement.append(host);
    const status = shadow.querySelector("#status"),
      fill = shadow.querySelector("#fill");
    const routeWatch = setInterval(() => {
      if (
        !/^\/(us|au|eu|ca)\/courses\/\d+\/discussion\/new\/?$/.test(
          location.pathname,
        )
      ) {
        host.remove();
        clearInterval(routeWatch);
      }
    }, 1000);
    shadow.querySelector("#close").onclick = () => {
      host.remove();
      clearInterval(routeWatch);
    };
    if (draft.image) {
      shadow.querySelector("#download").href = draft.image;
      shadow.querySelector("#copy").onclick = async () => {
        try {
          const blob = await adapter.pngFile(draft.image);
          await navigator.clipboard.write([
            new ClipboardItem({ "image/png": blob }),
          ]);
          status.textContent =
            "Screenshot copied. Paste it into the thread editor.";
        } catch {
          status.textContent =
            "Clipboard access was unavailable. Download the image and insert it through Ed.";
        }
      };
    }
    fill.onclick = async () => {
      fill.disabled = true;
      try {
        if (Date.now() - draft.createdAt > 30 * 60 * 1000)
          throw Error("This draft expired. Capture the exercise again.");
        status.textContent = "Filling your question and attaching the image…";
        const result = await api.runtime.sendMessage({ type: "FILL_ED" });
        if (!result?.ok || !result.value?.filled)
          throw Error(
            result?.error || result?.value?.error || "Ed could not be filled.",
          );
        if (draft.image) {
          status.textContent = result.value.attached
            ? "Title, question, and image are ready. Review the thread and click Post when you’re ready."
            : "Title and question filled. Automatic image attachment could not be confirmed; use Copy screenshot or Download image below.";
          shadow.querySelector("#fallback").hidden = !!result.value.attached;
        } else
          status.textContent =
            "Title and question are ready. Review and click Post when you’re ready.";
      } catch (error) {
        status.textContent = error.message;
        fill.disabled = false;
      }
    };
  }
  start();
  // Ed may redirect through login or change routes without a full navigation.
  const timer = setInterval(() => {
    if (started) clearInterval(timer);
    else start();
  }, 1500);
  setTimeout(() => clearInterval(timer), 30 * 60 * 1000);
})();
