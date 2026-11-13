# Production build verification — 1.2.0

## Application mode

This release uses the real Django API for all shared records and uploaded files. The browser-demo adapter, IndexedDB file store, sample-data generator, automatic example login, and role-switching shortcuts have been removed. A fresh installation starts with no accounts or classes. Device storage is used only for preferences and temporary unsaved exam choices; the server remains authoritative.

## Automated checks

- The Django suite has **47 passing tests**: the original account/sharing/folder/assignment tests; exam, call, result-release and analytics tests; production worker/readiness/login-throttling/storage checks; and deployment-secret validation.
- React production build and Python compilation passed. Django migrations are current.
- `tests/runtime_smoke.py` passed against the actual production supervisor, **Gunicorn, Django, and a temporary on-disk SQLite database**, with production settings and a trusted HTTPS-proxy simulation.
- Independent teacher/student HTTP clients registered their own accounts, joined a class, shared a nested-folder resource, submitted an assignment, and saved a grade. Secure and HttpOnly session-cookie attributes were verified.
- The server-only exam check started an attempt, saved an answer, and stopped all exam/state/results requests. The independent worker finalized the attempt at the deadline and awarded the correct marks. A late answer change did not alter the grade.
- After the complete server/scheduler process was stopped and restarted, the same sessions, class memberships, uploaded bytes, assignment grade, and exam result remained available.
- All six notification categories reached the enrolled student. The backup command produced a private archive containing the SQLite snapshot and referenced media, and every manifest hash matched its archived bytes.
- Production startup passed Django's deployment checks. Missing/stale worker heartbeat and unavailable upload storage fail readiness instead of reporting success. A low-disk upload is rejected before creating a resource record.

## Browser verification

The updated React sign-in page was rendered against the real Django API, with no demo badge or role-switching shortcuts. The browser reached `/api/health/` and received version 1.2.0 with database/storage ready. The development command now starts React, Django, and the exam scheduler together so the browser can reach the actual backend.

Teacher/student business workflows were tested over real HTTP as described above. Earlier browser interaction checks covered the exam builder, saved-answer resume, countdown/submission, result graphs, student ranking/review, notifications, and Jitsi pre-join launch. Those earlier checks preceded removal of the browser adapter and are not presented as a fresh browser login/session test of this release.

## Verification limits and deployment status

- The Docker engine is unavailable in this workspace, so the Docker image and Compose stack were not built/run here. The Python startup process used by the container was exercised directly with the production HTTP workflow.
- Render is not connected in this session; a paid service/disk has not been provisioned and this real Django release has not been deployed to a public production host. The existing static preview link cannot execute Django.
- The Render Blueprint and deployment instructions are included for deployment after connecting the host and reviewing its cost. This source package has not been pushed to an external repository; the existing GitHub repository is unchanged.
- A two-person live microphone/camera call, provider host authentication, mobile-device browser run, and desktop notification permission were not exercised.
- The application stores notifications in its inbox. Email verification/password recovery, email/SMS delivery, and background push require a configured provider and are not included.

The source archive excludes database files, uploads, backups, credentials, test account data, installed packages, virtual environments, and preview-only environment settings.
