# Courses and Canvas publishing

Trellis is the content and learning workspace. Canvas can keep its assignment
list and gradebook. Students can work directly in Trellis; ordinary assignment
creation does not require an LTI launch.

## Build a course

1. Open **All courses → Create a course**. Enter a title, optional code, term,
   and description. Existing instructors and platform administrators can create
   courses; the creator becomes the new course's instructor. TAs and students
   cannot create courses or promote themselves.
2. Choose **Add course content / Edit course structure**. Add sections and
   parts, then **Save changes**. Use Undo or Discard before saving a structure
   change.
3. Open a part's **Config → Content**. The content builder supports text,
   code examples, video links, coding instructions, multiple choice, select-all,
   and fill-in-the-blank questions. Choose correct answers in the builder;
   set the part's total points under Grading. Advanced JSON remains available
   for complex formatted content and grading definitions. Existing rich content
   is preserved unless explicitly edited.
4. **Save** creates a revision. **Preview** uses the student renderer.
   **Publish** makes the saved revision available to students. Coding files
   remain editable in Config, with student, grader, and solution visibility
   determined by their paths, as before.
5. Enroll people in this course from Course settings. An account can have a
   different role in each course. Registration alone no longer enrolls an
   account in whichever course was created first.

The bundled CS 1301 course remains the proof of concept. New courses start
empty and use generic section cards rather than CS 1301's unit names. Content,
rosters, progress, grades, accommodations, API tokens, and Canvas mappings are
scoped to their course. URLs include `course=<id>`; opening two courses in
different tabs does not change the other tab's selection. Active timed quizzes
prevent switching to another course's outline.

## Optional Canvas setup

The local course builder works without Canvas. To enable real publishing, add
the following to the ignored `.env` using credentials authorized to manage the
intended Canvas course:

```dotenv
CANVAS_BASE_URL=https://your-institution.instructure.com
CANVAS_API_TOKEN=your-private-token
TRELLIS_PUBLIC_URL=http://localhost:5173
```

Recreate the backend and Celery containers to load changed environment variables:

```sh
docker compose up -d --force-recreate backend celery
```

Tokens are server-only; they are not accepted in the browser UI or committed to
Git. Use **Course settings → Publish to Canvas** to save the Canvas course ID
and the Trellis site URL for this course. The course-specific URL overrides the
environment default. HTTPS is required except for localhost development.
A localhost link only works on the computer running Trellis; use a hosted URL
before sharing with students.

## Publish assignments

Set deadlines under **Assignments & grading**, then select sections in
**Publish to Canvas**. The preview lists each section's title, published parts,
point total, deadline, Trellis link, and existing Canvas mapping.

One section becomes one Canvas assignment. Its points are the sum of its
published graded parts, matching the existing Trellis grade synchronization
unit. Unpublished revisions and deleted parts do not contribute. Empty sections
cannot be sent. The description contains a direct, course-specific Trellis
link; it never contains solutions, grader files, or quiz questions. Canvas uses
`submission_types: ["none"]` and points grading: submissions happen in Trellis.

**Create / update Canvas drafts** is the default. Check **Publish in Canvas**
to make the selected assignments visible immediately. Trellis's own visibility
and quiz access rules still apply, including for sections hidden from students.
The operation does not push student grades. The existing **Gradebook → Sync
grades to Canvas** action uses the mappings saved by assignment publishing and
still needs each student's Canvas user ID.

Repeat publishing updates the mapped assignment with `PUT`; it does not create
a fresh assignment. Existing Canvas assignments can be linked by ID. Once a
course has assignment mappings, changing its Canvas course ID is blocked to
avoid retargeting grade updates into a different course. Assignment description,
name, points, due date, and published state are managed by this explicit action;
unrelated Canvas settings and overrides are not replaced.

A reservation is saved before sending a request. A concurrent click is blocked.
If a create times out or returns an ambiguous response, Trellis records **Check
Canvas** and refuses to repeat the create. Check whether Canvas created the
assignment, then use **Link an existing assignment** to recover its ID. An
interrupted in-progress reservation can be linked after 60 seconds, beyond the
network request timeout. If Canvas did not create it, staff must inspect and
clear the reservation deliberately; there is no blind create retry. Rate limits
and other confirmed errors are shown without exposing remote bodies or tokens.
Batch publishing runs one assignment at a time with progress and individual
results. Leaving the page stops subsequent assignments; an already-sent request
can still finish.

The integration uses Canvas's documented [Create and Edit Assignment REST
endpoints](https://developerdocs.instructure.com/services/canvas/resources/assignments).
Canvas credentials need access to create/update assignments in the chosen
course. Grade synchronization additionally requires submission grade access.
Live publishing requires a real authorized Canvas connection; local tests use
mocked Canvas responses.

## Browser API endpoints

These endpoints use the signed-in session and CSRF protection for writes.
Send `X-Trellis-Course: <id>` for course-scoped operations. Invalid or unenrolled
course IDs are rejected, never silently replaced by another course.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/courses/` | List this account's active course memberships |
| POST | `/api/courses/` | Create a blank course; title/code/term/description |
| GET / POST | `/api/settings/course/` | Read / update selected course identity |
| GET | `/api/settings/canvas/assignments/` | Read connection status and assignment preview |
| POST | `/api/settings/canvas/configure/` | Save `canvas_course_id` and `trellis_url` |
| POST | `/api/settings/canvas/assignments/<id>/publish/` | Create/update one Canvas assignment; `{ "published": false }` |

Existing `/api/v1/` bearer tokens remain restricted to the course in which they
were issued. A browser course selector or header cannot expand their scope.
