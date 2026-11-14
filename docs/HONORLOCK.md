# Honorlock Universal programming quizzes

Trellis implements the password handoff for Honorlock Universal third-party
assessments. Trellis does not need to be an LTI tool. Students launch proctoring
from Honorlock in Canvas, navigate to the direct Trellis quiz link, sign in if
needed, and use Honorlock's **Unlock assessment** control to populate the standard
password input. Clicking **Unlock and begin quiz** starts the Trellis timer.

## Register a test assessment

1. In Trellis, open **Course settings → Programming quizzes** and select the quiz.
   Enable **Exam mode**, set a time limit, and publish it to the intended students.
2. Under that quiz's **Honorlock** controls, generate a unique password and copy it.
   Enable **Require Honorlock unlock**, then **Save Honorlock settings**. Copy the
   **Direct exam URL**. Passwords are stored only as hashes: keep the copied value
   long enough to configure Honorlock; changing it later requires updating both.
3. In Canvas → Honorlock, choose **Register Third Party Assessment**. Use the exact
   Trellis quiz title, **Use Another Platform → Trellis**, the copied direct URL,
   and exactly the same exam password. Do not distribute this password to students.
4. Match Honorlock's access window to the intended assessment schedule and configure
   its proctoring settings, instructions, and accommodations. Trellis's quiz time
   limit and accommodation controls determine the in-platform timer. A time limit
   is a duration, not an availability window. Allow the Trellis hostname in any
   Honorlock website restrictions and include the login flow when testing.
5. Use an enrolled test student in Chrome with the Honorlock extension. Launch
   Honorlock first, complete authentication, open the Trellis link, and sign in.
   Confirm the URL still points to the same quiz after sign-in.
6. At Trellis's password prompt, use **Unlock assessment** in Honorlock, then click
   **Unlock and begin quiz**. Confirm the timer starts at this step, not while
   logging in or completing Honorlock setup. Run and Submit remain repeatable. The numbered quiz navigator and Previous/Next question controls switch between all questions while course navigation remains locked. Code edits save before switching questions. Trellis never requests fullscreen.
7. Submit the entire quiz. Confirm only the score and closed screen remain, then
   return to Honorlock to finish the proctoring session as instructed there.

No existing quiz is switched to Honorlock automatically by deployment. Staff can
inspect content in normal staff mode. **Enter student view** exercises the actual
gate; **Reset my test attempt** resets only that staff member's test work and score.
Never use a real student's attempt for a setup test.

## Enforced by Trellis

- An active course enrollment and student-visible quiz are required.
- Questions, question titles in the outline, starter files, saved workspaces,
  Run, Submit, hints, and execution results remain unavailable until unlock.
- Successful unlock is recorded in the authenticated server session, bound to the
  quiz's access configuration version. It is not a browser-only flag.
- Logging out or changing the quiz password requires another unlock. Existing
  attempts retain their original start/expiry timestamps. Reloading an unlocked
  session neither starts another attempt nor resets the timer.
- Ten failed password checks in 15 minutes lock that account/quiz combination for
  15 minutes. Counters are in PostgreSQL and survive processes or replica changes.
- Passwords must be 16–128 printable ASCII characters, without spaces or quotation
  marks. Generate password produces 48 random hexadecimal characters.
- The password/hash never appears in course metadata, student payloads, or the
  settings response. Only staff can replace the password or enable the requirement.
- Attempts close at expiry or whole-quiz submission. Repeated per-question Run and
  Submit requests are allowed before closure. Accepted jobs may finish processing
  after their request was accepted. Closing does not expose student sample answers.
- Password rotation revokes prior session unlocks without changing scores or timers.
  Avoid rotating during a real assessment except when intentionally revoking access.

## Limits of the Universal integration

This is a password handoff, not an Honorlock session-verification SDK. Trellis cannot independently attest that the extension is recording or detect a
stopped recording. It now makes a best-effort completion notification using the
official `@honorlock/integration-sdk-js` 1.5.1 package: initialize the extension
bridge while an unlocked quiz is active, then register the submission callback
and invoke `examSubmit()` only after the backend confirms final submission. No
API credentials, new session setup, identity, questions, or code are sent.
The SDK does not acknowledge that recording actually stopped. Canvas Universal
compatibility remains an external test requirement; initialization failure or
extension rejection leaves a clear Exit Honorlock fallback. An SDK notification
is not a substitute for the End Exam Session API in a full custom integration. Proctoring enforcement and records
remain in Honorlock. The test assessment must verify actual extension autofill,
website restrictions, and completion behavior before using this for a real exam.
Trellis does not install the extension, request camera/microphone access, or accept
Honorlock agreements for anyone. No student proctoring data is copied into Trellis.

## Implementation

- `QuizAccessConfig`: per-lesson enabled flag, password hash, version; separate
  from authorable/exportable metadata. New quizzes/copies have no access config.
- `QuizUnlockFailure`: per-membership/quiz failure counters and lockout timestamp.
- Migration `0013_quiz_honorlock_access` creates only these two new tables.
- Staff POST `/api/settings/quizzes/<quiz_id>/honorlock/`:
  `{"enabled":true,"password":"<unique quiz password>"}`. Omit/blank password to
  keep an existing hash. Disable with `{"enabled":false}`. CSRF is required.
- POST `/api/quizzes/<quiz_id>/start/` accepts `{"password":"..."}`. If already
  unlocked in that session, no password is required. The attempt is created only
  after access is granted. Staff authoring bypass does not apply to student view.
- GET `/api/quizzes/<quiz_id>/status/` adds `honorlock_enabled` and `access_required`;
  no secret or token is returned. Quiz status and staff settings are not cached.
- Run the isolated tests in `backend/core/tests/test_honorlock.py` alongside the
  full backend suite; frontend build and browser checks cover the standard input,
  wrong-password feedback, successful unlock, timer, and closed result screen.

Vendor documentation:
- [Create a Third Party Exam](https://honorlock.kb.help/create-a-third-party-exam/)
- [Universal Exam test-taker instructions](https://honorlock.kb.help/how-to-use-honorlock-with-a-universal-exam-test-takers/)

## Quiz navigation regression

Exam mode hides the course sidebar, not the quiz's question controls. The top
navigator includes Previous/Next, all numbered questions, current position/total,
and full-credit markers. The footer remains available. All quiz questions are
included even if imported with different content categories. Switching questions
autosaves edited workspace files first; a failed save keeps the current question
open. Course/assignment navigation remains locked while the exam is active.
Trellis no longer requests or exits browser fullscreen for programming quizzes.

The submission signal is sent only for whole-quiz submission, not per-question
Submit. Time expiry still closes Trellis access; it does not claim Honorlock has
ended. The final screen always distinguishes a sent signal from stopped recording.

The quiz navigator includes an automatically refreshed total, earned/maximum
points on each question, and full-credit/partial-credit/in-progress/not-started
states. Full credit is based on recorded points, not merely viewing or running
a question. Compact fractional points are preserved. Exam mode uses the full
page width instead of reserving space for the hidden course sidebar.
