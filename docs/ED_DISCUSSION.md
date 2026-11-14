# Ed Discussion extension

Students use the **Trellis · Ask on Ed** browser extension. The manual-copy Ask on Ed
button has been removed from the course page. Staff still configure the course URL
under **Course settings → Integrations → Ed Discussion**; clearing it disables capture.
No discussion board is configured in the local demo. An instructor may configure their own board in Course settings if using this optional integration.

See [extension setup and privacy](../extensions/trellis-ed/README.md) for installation,
Safari packaging, permissions, limits, and development commands.

## Student flow

1. Open a regular exercise or sandbox in Learn view and click the extension.
2. Review its suggested title and cropped exercise screenshot; type the question.
3. Optionally include the visible code workspace and capture again.
4. Continue to Ed. The exact configured course's new-thread editor opens.
5. Select **Fill draft & attach image** in the assistant. It fills title/body and
   uploads the PNG through Ed's own image-paste handler and existing login.
6. Review the image, select a category if necessary, and click Post in Ed.

No Trellis link is included in the body. Full exercise text can optionally be included as context;
the screenshot contains only the visible exercise area. Screenshot selection is
shown before upload. The extension never posts automatically or overwrites another
draft. A new loaded HTTPS image is required before reporting attachment success.
If the editor changes, explicit copy/download fallbacks remain available.

Programming quizzes, Config view, and staff Preview mode fail closed. The helper
reads no private backend data, grader files, hidden solutions, or authentication
credentials. Opting into a workspace screenshot can share the visible student code
and output; the student must review this before continuing.

## Platform contract

- Course metadata remains `ed_discussion_url`.
- Existing staff-only GET `/api/settings/ed-discussion/` and CSRF-protected POST
  `/api/settings/ed-discussion/save/` remain unchanged.
- Activity detail exposes only the validated permitted course URL; quizzes receive null.
- `App.tsx` exposes a minimal versioned DOM contract on the visible activity body:
  `data-trellis-ed-version="1"`, `data-allowed`, kind/title/assignment/activity/lesson,
  course Ed URL, and exact student route. No private content is added to the DOM.
- `data-trellis-ed-instructions` marks the source pane, and
  `data-trellis-ed-workspace` marks the optional visible workspace area.
- Capture requires an explicit allowed marker and validates both URLs. It checks
  source identity and geometry again after screenshot capture to reject route/scroll races.
- Runtime source lives under `extensions/trellis-ed/src`; packages are generated
  under its ignored `dist/` directory. Chrome/Brave/Edge use Manifest V3; Safari uses
  separate nonpersistent background-page resources and Apple's Xcode converter.

## Verification

The extension was loaded in Brave with the owner's explicit approval. On the CS1301
sandbox board, a synthetic test question was filled with real paragraphs, Python
comments preserved, and a cropped image uploaded automatically. The owner explicitly
authorized posting, and thread `8495843` was posted with the image and no Trellis link.
No student records or grades were involved. Chrome/Edge share the packaged source
but have not separately been exercised; Safari still requires Xcode, signing, and
actual browser testing. Do not describe the Safari resources as a signed app.
