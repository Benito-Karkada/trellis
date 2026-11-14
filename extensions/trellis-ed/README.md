# Trellis · Ask on Ed

A local-first WebExtension for sharing a regular Trellis exercise with Ed Discussion.
The extension opens a preview with an editable title, question, and cropped image.
Continue opens the configured Ed course; **Fill draft & attach image** fills the
empty editor. The student reviews the result and posts using their existing Ed
login. No Trellis link is added to the post.

## Development installation (Chrome, Brave, Edge)

From this directory:

```sh
npm ci --ignore-scripts
npm run package
npm test
```

Open the browser's Extensions page, enable Developer mode, choose **Load unpacked**,
and select `dist/chromium`. Pin **Trellis · Ask on Ed** if desired. After source
changes, package again and click Reload on the extension's card. Reload closes
extension preview tabs; capture a fresh exercise afterward.

Open a regular exercise or sandbox in Trellis Learn view and click the extension.
If part of the instructions is offscreen, scroll Trellis to the desired area and
use Capture again. Optionally include the full extracted instruction text; the default post contains the question, exercise/assignment names, and screenshot.
Optional **Include the visible code workspace** expands the screenshot only after
Capture again. Preview your code before sharing it with classmates.

## Safari

`dist/safari` contains the Safari WebExtension resources, not an installable app.
Install the full Xcode app, select it as the developer directory, then run:

```sh
sh tools/package-safari.sh
```

This invokes Apple's converter to generate a macOS Xcode project. Open it, select
an appropriate signing team, build the containing app, and enable its extension
in Safari. Development testing may require Safari's unsigned-extension option.
A signed app/TestFlight/App Store distribution and actual Safari QA are required
before student rollout. Command Line Tools alone do not include the converter.
No Apple signing identity or account is bundled here.

## Privacy, permissions, and behavior

- `activeTab` and `scripting`: read/capture Trellis only after the extension is clicked.
- Persistent host permission: exactly `https://edstem.org/*`, for the draft assistant.
- `storage`: at most two local screenshot drafts; no sync storage or telemetry.
- `clipboardWrite`: explicit screenshot-copy fallback only. No clipboard reads.
- No cookie, history, debugger, network interception, broad tabs, or all-sites permission.
- Programming quizzes, Config view, and staff Preview mode are excluded by a
  fail-closed Trellis DOM contract. No backend files or grader endpoints are read.
- Only the visible cropped exercise area is retained, never the whole browser image.
- Drafts expire after 30 minutes; expired records are removed at the next extension
  action/message. Discard removes the local draft immediately. Browser-local data
  may remain on disk until this cleanup or removal of the extension.
- Each draft is bound to its preview tab, destination Ed tab, and exact course.
- Ed integration uses visible DOM fields and Ed's own image-paste upload handler;
  no Ed API credentials or internal application state are used. Editor insertion
  runs as a packaged function in the page's MAIN world so native clipboard event
  types match Ed's editor. No remote code/eval is used.
- Never clicks Post automatically or overwrites an existing nonempty draft.
- Upload success is only reported after a new HTTPS image loads in Ed. If that
  cannot be confirmed, the assistant provides Copy screenshot / Download image.
- Ed may autosave unposted drafts and upload image attachments when you fill it.
- New Trellis domains must be added to `src/common.js` and repackaged. HTTP localhost/127.0.0.1 are supported.

## Tests

The Node tests cover trusted origins, exact Ed destinations, quiz/config denial,
text extraction, code indentation, removal of hints and typed answers, draft
expiry, tab binding, screenshot cropping, overwrite protection, and permissions.
`tests/exercise.html` is a synthetic browser-test fixture. No real student data
is needed. Runtime packages contain only files from `src/`.

This extension is not published to a browser store. Store publication/signing is
separate from preparing these packages.

## POC verification

The local frontend includes exercise capture support.
