# Trellis security and roles

Security hardening reviewed 2026-11-09. This is a scoped engineering review, not a penetration-test certification or a guarantee of no vulnerabilities.

## Private data contract

Student responses use explicit allowlists. They must never expose raw grading rules/answer keys, staff/grader/quarantine files, raw XML/archives/import warnings, API or Canvas credentials, other students' work, or staff review records. Released hints and sample answers follow the exercise/quiz release rules.

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

## Application protections

- Session authentication and CSRF enforcement on cookie-based changes. Bearer APIs require scoped tokens, not session-cookie authentication.
- Active course membership checks, private grader/staff files, closed-quiz access controls, course-scoped API records.
- Login limits shared in PostgreSQL across workers: 20 requests per hashed account bucket per five-minute window, and 2,000 across the deployment. 429 includes Retry-After. Fixed HMAC shards bound the counter table to 16,385 rows. Counters retain no emails, passwords or client IPs. Rare hash collisions share a short-lived limit. This is deliberately independent of untrusted forwarded-IP headers.
- 2.5 MB JSON/form-body memory limit, bounded CSV inputs; file-upload memory setting controls spooling, not total file size. Native/API file validation remains necessary. A proxy/WAF body-size limit is still needed before the app.
- Private API/admin cache controls; secure, HTTP-only session cookies; SameSite=Lax; eight-hour sessions; nosniff, frame denial and one-day HSTS on Azure. No HSTS subdomain/preload commitment.
- Existing execution protections: one queued/running job per account, reset blocked during execution, bounded output, execution timeout, two worker slots and isolated non-networked student containers. Student Python never runs in the web process.

## Azure isolation and database credentials

- PostgreSQL `cs1301-poc-db27`, Blob storage and Key Vault have public network access disabled. Course assets stay in a private container.
- The grader's NSG denies inbound traffic and outbound VirtualNetwork traffic. It receives no application/database/Canvas credential. Worker authentication uses its dedicated token.
- PostgreSQL connections validate the server certificate and hostname (`verify-full` with the OS CA bundle), verified against the live server using TLS 1.3.
- Web runtime uses `trellis_runtime`: DML on application tables/sequences, no schema CREATE, no database/role administration, connection limit 16. Schema migrations require a separately authorized deployment/maintenance connection using the administrator credential. Do not temporarily turn the web app back into an administrator as a routine deployment step.
- `scripts/bootstrap-runtime-db.py` is trusted maintenance code to provision/rotate the restricted role. Its password must be injected securely. Never run student code with this script or put credentials into Git. The normal repair/deploy helper preserves the runtime secret reference.
- Review Azure subscription/RG access separately: a course role does not grant Azure access. Shared RG contributors can change infrastructure; move production into dedicated ownership/RBAC scope. Prefer managed identity and Key Vault over stored SAS/registry credentials when the team has permission to assign roles.

## Edge DDoS/WAF work still required

Application rate limits cannot absorb a volumetric or distributed attack. The current Container Apps endpoint is directly public over HTTPS and has no dedicated Front Door/WAF configured. Microsoft.Cdn was NotRegistered during this review.

Recommended POC deployment: Front Door Standard, a custom WAF policy with tuned login/API rate rules, no caching on /api or /admin, and logs/alerts. Standard's published base price is USD35/month plus usage and applicable WAF charges. Managed OWASP/bot rules and Private Link origin protection require Premium (published base USD330/month plus usage); obtain a concrete budget/ownership decision before provisioning.

A protected hostname alone is insufficient: lock down the Container Apps origin too, using supported Front Door backend source restrictions and validation of the specific X-Azure-FDID, or Premium Private Link. Container Apps CIDR restrictions are not App Service service-tag rules; use the correct supported implementation. A header check alone is spoofable. Preserve worker callbacks, health probes, Honorlock, Kaltura and authorized maintenance while testing the cutover. Do not geo-block international students or use aggressive IP limits that lock out students sharing GT/NAT addresses.

References:
- https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- https://learn.microsoft.com/azure/frontdoor/secure-front-door
- https://learn.microsoft.com/azure/frontdoor/origin-security
- https://learn.microsoft.com/azure/frontdoor/understanding-pricing
- https://learn.microsoft.com/azure/postgresql/security/security-tls-how-to-connect

## Remaining verification

No broad external penetration test, credential-leak history audit or certified FERPA review was performed. GT CAS/Duo, edge WAF/origin restrictions, dedicated production Azure ownership, automatic security alerting, storage credential rotation/retention and periodic restore drills remain production-readiness work. Timing/focus review signals are not proof of misconduct. Re-run dependency audits and permission tests regularly; an advisory-free audit is a point-in-time result, not proof that dependencies are safe.

## Verification from this change

216 backend tests passed, including role escalation, metadata deadline bypass, token demotion, preview boundaries, CSRF, login and admin-login throttling. The frontend build passed. Audits of the final frontend lockfile and 42 installed Python packages in image `poc-v57` reported zero known advisories at review time. Live checks and deployment status are recorded separately under ignored operational artifacts.

Live verification completed successfully on revision `cs1301-poc-web-v2--security-1794269380`: HTTPS/security headers, instructor login, shared API/admin brute-force limits, restricted database role and TLS, isolated Run/Submit errors/timeouts/output bounds, points/results/sample reset behavior, sandbox and quiz access. Disposable integration-test accounts and records were removed by the smoke test. Deployment-check warnings W008/W005/W021 are intentional: HTTPS is enforced at Container Apps ingress, and HSTS does not include subdomains or request preload.
