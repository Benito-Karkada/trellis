import {
  mkdir,
  readFile,
  readdir,
  copyFile,
  writeFile,
  rm,
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
import { execFileSync } from "node:child_process";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ed = "https://edstem.org/*";
for (const platform of ["chromium", "safari"]) {
  const out = resolve(root, "dist", platform);
  await rm(out, { recursive: true, force: true });
  await mkdir(out, { recursive: true });
  for (const file of await readdir(resolve(root, "src")))
    if (file !== "manifest.json")
      await copyFile(resolve(root, "src", file), resolve(out, file));
  const manifest = {
    manifest_version: 3,
    name: "Trellis · Ask on Ed",
    version: "0.1.0",
    description:
      "Bring a Trellis exercise, question and screenshot into an Ed Discussion draft.",
    permissions: ["activeTab", "scripting", "storage", "clipboardWrite"],
    host_permissions: [ed],
    action: {
      default_title: "Ask about this exercise on Ed",
      default_icon: { 16: "icon-16.png", 32: "icon-32.png" },
    },
    icons: {
      16: "icon-16.png",
      32: "icon-32.png",
      48: "icon-48.png",
      128: "icon-128.png",
    },
    background:
      platform === "chromium"
        ? { service_worker: "background.js", type: "module" }
        : { scripts: ["background.js"], type: "module", persistent: false },
    content_scripts: [
      {
        matches: [ed],
        js: ["ed-content.js"],
        run_at: "document_idle",
        all_frames: false,
      },
    ],
    web_accessible_resources: [{ resources: ["ed-page.js"], matches: [ed] }],
    content_security_policy: {
      extension_pages:
        "script-src 'self'; object-src 'none'; connect-src 'none'; img-src 'self' data:; style-src 'self'",
    },
  };
  await writeFile(
    resolve(out, "manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n",
  );
  execFileSync(
    "/usr/bin/zip",
    ["-qr", resolve(root, "dist", `trellis-ed-${platform}-0.1.0.zip`), "."],
    { cwd: out },
  );
  console.log(`Packaged ${platform}: ${out}`);
}
