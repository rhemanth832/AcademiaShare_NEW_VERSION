# Academia Share

A server-backed classroom application built with **React, Django, and SQLite**. Every account, class, folder, uploaded file, assignment, exam, grade, and notification is stored by Django. Users on different devices share the same server data.

This version has no browser-demo backend, automatic sample login, account-switching shortcut, preloaded classes, or fake student results. A fresh installation starts empty. Each teacher and student creates an account and signs in normally.

## Start locally

Install Python 3.10+ and Node.js 20.19+ or 22.12+, extract the source, and run:

```bash
python start.py
```

Open `http://127.0.0.1:8000`. Create a teacher account and a separate student account. Teachers create classes and share invite codes; students join using those codes. The command installs dependencies, builds React, migrates SQLite, starts the real API, and starts the exam scheduler. Accounts and uploads remain on disk after it stops. First-time installation needs an internet connection.

Local startup is for use on your machine. Use the production deployment below for students to access the application over the internet.

## Deploy the real application

Use a Python/container host with persistent storage. **The old static preview URL cannot execute this Django application.** Uploading the React build alone does not create an application server.

The repository includes:

- `Dockerfile`: React build stage, pinned Python dependencies, Gunicorn, and an application bootstrap that drops root privileges after preparing the volume.
- `render.yaml`: one Docker web service in Singapore with a persistent disk for SQLite and private uploads, generated secret, HTTPS-proxy settings, and an HTTP health check. A paid service/disk is required; review the host's price before creating it.
- `compose.yaml`: self-hosted deployment behind an HTTPS reverse proxy, with a named persistent volume and a localhost-bound application port.
- `ops/run_server.py`: migrations, cache-table creation, SQLite WAL configuration, static collection, production checks, and supervision of Gunicorn plus the exam worker.
- `DEPLOYMENT.md`: host configuration, upgrade, backup, and restore instructions.

Upload the extracted application to a repository you control, then connect that repository to Render and apply its `render.yaml`. The supplied Blueprint expects the application at the repository root. If you choose to place it in a `production/` subdirectory, set `rootDir: production` on the service. This source package has not been pushed to an external repository.

Render supplies `RENDER_EXTERNAL_HOSTNAME`; Django uses it for host validation and trusted HTTPS origins. Its generated 256-bit base64 secret is expanded deterministically with SHA-256 for Django's key-length check. Set additional exact hostnames/origins for a custom domain. Never put secrets in source control.

## Features

- Separate teacher and student registration/login, Django password hashing, server sessions, CSRF protection, profile changes, password changes, and sign out.
- Teacher-owned classes, invite codes, membership checks, teacher student lists, and role-specific dashboards.
- Private libraries and teacher-to-class sharing; folders/subfolders, breadcrumbs, rename/move, sorting, search, starred resources, and recent files.
- Multipart uploads up to 25 MB each, per-user quota checks, disk-capacity checks, protected downloads, and document/image/text/audio/video previews.
- Recoverable trash for files and folder trees, and explicit permanent deletion.
- File assignments, deadlines, points, optional late work, student submissions, teacher grading, and feedback.
- MCQ exam creation with 1–100 questions, 2–6 choices, one correct answer, custom marks, and explanations.
- Teacher-controlled appearance time, start time, final deadline, early opening, attempt duration, and result-release policy.
- One resumable attempt per student, answer autosave, server-controlled expiry, automatic submission/grading, and hidden solutions until release.
- An independent exam scheduler, supervised with the web server; students do not need to keep a browser open for grading.
- Attendance, appeared/submitted/not-started students, marks, correct/wrong/unanswered answer reviews, question graphs, participation charts, marks distributions, top-10 rankings, and CSV exports.
- Teacher class insights and private student result pages.
- Scheduled/immediate video sessions, teacher start/end controls, and protected join links for Jitsi or another HTTPS meeting provider.
- Notification inbox for resources, announcements, assignments, exams, results, and video sessions; filters, unread counts, direct links, and optional browser alerts.
- Real database/storage/scheduler health checks and administrator-run database/media backups.

## Exam behavior

The server hides an exam until its appearance time and rejects starts before its start time. A teacher can open it early. Starting creates one attempt with expiry equal to the earlier of `attempt start + duration` and the final deadline. A refresh never resets the timer.

Choices save to Django while students work. Unsaved choices can be kept temporarily on the student's device for reconnecting; they count only if the server receives them before expiry. Late payloads cannot change saved answers. Correct answers and explanations follow the teacher's result-release policy. Published questions are fixed so everyone is graded on the same paper.

The production exam worker checks expiry every 15 seconds and grades saved answers independently of browser activity. An unhealthy or stopped worker fails readiness and causes the supervising service to restart. State/results requests also finalize an expired attempt as a recovery path. Timeout finalization never extends the original deadline.

Class rankings use the percentage earned on a student's submitted exams and graded assignments; ungraded students are unranked. This is a progress measure, not a final course grade. Exam rankings sort by marks, then shorter completion time, then student ID.

## Video and notifications

Calls open through the chosen meeting provider. Jitsi may require the teacher/first participant to authenticate. The application checks membership before returning a live meeting URL. The provider handles camera/microphone, moderation, and participant admission. Ending the application listing removes its join button; the host must also end the provider meeting to disconnect participants.

Classroom updates are saved in the database and available when a student next signs in. The inbox refreshes while the workspace is open. Optional browser alerts require browser permission and an open workspace. Background push, email/SMS delivery, email verification, and email password recovery are not configured. An administrator can manage accounts through Django admin.

## Development and checks

```bash
python start.py --setup-only
npm run dev
```

The development command starts Vite, the real Django API, and the exam worker together. It does not substitute browser storage for the backend.

```bash
# Windows: use .venv\Scripts\python.exe instead of .venv/bin/python
.venv/bin/python backend/manage.py test core --noinput
npm run build
.venv/bin/python tests/runtime_smoke.py
```

The runtime check starts the actual production supervisor on a temporary port with temporary accounts/data. It checks independent clients, secure sessions, file sharing, assignments and grading, worker-driven exam expiry without browser requests, all notification categories, backups, and persistence across a complete server restart. See `VALIDATION.md` for results and verification limits.

## Data and scale

SQLite and media are under `ACADEMIA_DATA_DIR`. Production refuses to start without this explicit directory, a strong secret, and a valid hostname. The deployment uses one service instance and a single Gunicorn worker with four request threads. SQLite transactions serialize writes and use WAL for concurrent readers. For a larger, multi-instance institution deployment, migrate the database and file storage before adding instances.

Never delete the persistent volume during an upgrade. The source archive excludes all accounts, SQLite databases, uploaded files, backups, credentials, virtual environments, installed packages, and preview-specific configuration.
