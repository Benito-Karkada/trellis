# Trellis security and roles

## Private data contract

Student responses use explicit allowlists. They must never expose raw grading rules/answer keys, staff/grader/quarantine files, API or Canvas credentials, other students' work, or staff review records. Released hints and sample answers follow the exercise/quiz release rules.

## Course roles

| Capability | Instructor | TA | Student |
| --- | --- | --- | --- |
| View published lessons and own work | Yes | Yes | Yes |
| Edit/publish content, files, graders, course outline; configure quizzes | Yes | Yes | No |
| Review student grades, saved work and submission history; run teaching copies | Yes | Yes | No |
| Read course roster and review signals | Yes | Yes | No |
| Add/import/drop people or change roles | Yes | No | No |
| Provision/reset other accounts' passwords | Yes, except self/superuser | No | No |
| Set accommodations and assignment deadlines | Yes | No | No |
| Change course-wide feedback, review policy and integration settings | Yes | No | No |
| Bulk-push grades to Canvas | Yes | No | No |
| Issue scoped API tokens | Yes | Teaching scopes only | No |

TA is a trusted teaching/content-authoring role, not a read-only grader. TAs can change questions and grading definitions. Legacy `head_ta` has TA privileges, not instructor privileges. Django's administrative `is_staff`/`is_superuser` flags are separate from these course roles; do not grant Django administration merely to make someone a TA. Student view denies staff settings and work-review routes, regardless of underlying staff role. Bearer tokens recheck active membership and current role on every request, including after demotion.

## Local development boundaries

Services bind their published ports to `127.0.0.1`. PostgreSQL and Redis have no host-published ports. Database contents and private files use project-specific Docker volumes. The debug-only instructor shortcut and documented demo passwords are intended for local use.

Cookie-authenticated changes use CSRF protection. Student projections omit grading definitions and staff/solution files. The API rechecks course membership and role permissions. Generated `.env` secrets stay out of Git.

Student Python executes through the host worker in disposable Docker containers, never in the Django process. Sandboxes have no network, host-directory mounts or application credentials and have CPU, memory, process, output and time limits. One active job per account prevents accidental duplicate execution. Resetting a workspace is blocked while its job is active.

This is a local development setup. Do not expose its development ports or demo accounts to the public internet. Timing and focus signals are review information, not proof of misconduct.
