# Course grading controls

Open **Course settings → Assignments & grading**.

- Set each section/assignment's due date in your local time zone, or clear it for no deadline. It applies to graded content within that section. Individual activity/lesson/course deadline accommodations take precedence in that order.
- Submissions received after the applicable deadline still return answers, feedback, and coding results, but cannot increase or decrease recorded points or mark graded work complete. Coding receipt time determines credit even when the isolated worker finishes later. Moving a deadline affects future attempts; past practice is not automatically regraded.
- Change success and try-again headings/messages once for the whole course. Messages are plain text. The default success heading is **Well done!**, without an emoji. Quiz sample solutions remain staff-only.

## Non-coding answer explanations

Per-answer explanations are unavailable before a correct submission. A submitted wrong answer shows its feedback during the retry timer, including after a refresh. Once a question has been answered correctly, its choices become a review interface: clicking a choice displays its explanation without changing the submitted response, creating a submission, or changing points. Unlocks are per question, so a correct question in a multi-question exercise can be reviewed while the others are unfinished. General XML demand hints remain separate from answer-choice feedback.

## Student review

Click a student's name in **Gradebook** for the entire course, or a score to restrict review to one assignment. Use the assignment selector and part search in the review sidebar. Workspaces load when selected, rather than all at once. Run/Submit copy remains a staff review action and never changes student work or grades. Readings show **Ungraded**, not 0/0. The matrix shows 50 students per page and supports name/email search; By assignment selects a single assignment.

Entering/exiting student view retains the current route. Sections not available to students remain inaccessible in that view; switching back restores staff access without navigating Home.

## Canvas placeholder and future activation

**Sync grades to Canvas** is intentionally unconnected for this POC. Without server configuration it reports that nothing was sent. No real Canvas course or student mappings were configured by this change.

The adapter supports a server-side HTTPS `CANVAS_BASE_URL` and secret `CANVAS_API_TOKEN`, a Canvas course ID, per-section assignment IDs, and per-enrollment Canvas user IDs. Student identities belong to the Enrollment roster-sync workflow; there is no separate Canvas connection or manual student-ID form in Assignments & grading. Before activation, confirm that a Trellis section corresponds to one Canvas assignment; do not use one Canvas assignment ID for unrelated sections. Missing mappings block bulk sync. Tokens never enter browser forms.

A durable PostgreSQL outbox coalesces updates per student/assignment. A future application-side worker must run `python manage.py process_canvas_queue`; keep this worker away from the isolated Python execution VM. It retries network/HTTP failures with backoff (up to ten attempts) and saves no credential/response bodies in error logs. Manual sync queues all mapped recorded scores, including zeros; late practice never changes those scores or creates automatic grade updates. Do not enable external delivery without the instructor's approval of the target course and mappings.

Canvas REST grade delivery follows the [Canvas Submissions API](https://developerdocs.instructure.com/services/canvas/resources/submissions). The existing LTI AGS placeholder is separate from this REST adapter.


Manual Canvas grade sync adds `comment[text_comment]` in the same update as the
recorded grade. The comment uses delivery time in America/New_York, shows the
recorded points and either full-credit congratulations or time until the effective
deadline (including accommodations). Expired and missing deadlines get explicit
wording rather than a negative or invented countdown. Mixed remaining deadlines
point to the next deadline and tell students to check the individual exercises.
Routine automatic passback does not request comments. A queued manual comment is
preserved when newer scores coalesce, retained for retries, and cleared after
successful delivery. As with Canvas's append-only comment update API, a network
timeout after Canvas accepted a request can cause a duplicate comment on retry.
No Canvas requests are made while the integration is unconfigured.

Canvas reference: https://developerdocs.instructure.com/services/canvas/resources/submissions
