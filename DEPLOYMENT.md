# Production deployment

Academia Share serves React and Django from one origin. The application must run as a Python/container service with a persistent data directory. A static frontend deployment cannot run this version.

## Render

The supplied Blueprint requests a paid `starter` Docker web service and a 10 GB persistent disk. Confirm the current price before applying it; this source package does not purchase or create hosting.

For a repository containing the extracted app at its root, use the included `render.yaml` directly. If you later place the app in a `production/` subdirectory of an existing repository, set `rootDir: production` on the service. This source package has not been pushed to an external repository.

| Setting | Value |
| --- | --- |
| Runtime | Docker |
| Region | Singapore |
| Root directory | Repository root for the extracted app; `production` only if you put the app in that subdirectory |
| Dockerfile | `./Dockerfile` |
| Docker context | `.` |
| Instances | 1 |
| Health path | `/api/health/` |
| Disk mount | `/var/data` |
| Data directory | `ACADEMIA_DATA_DIR=/var/data` |
| Secret | Render generates a private 256-bit base64 `DJANGO_SECRET_KEY`; the app expands it deterministically for Django. For manual hosting, generate at least 50 random characters. |
| Production mode | `DJANGO_ENV=production`, `DJANGO_DEBUG=0` |
| HTTPS proxy | `DJANGO_TRUST_PROXY=1` |
| Exam worker readiness | `ACADEMIA_SCHEDULER_REQUIRED=1` |

Render supplies the public hostname automatically. For a custom domain, add it to `DJANGO_ALLOWED_HOSTS` and its complete HTTPS origin to `DJANGO_CSRF_ORIGINS`. Do not use a wildcard host. The provider's TLS-terminating proxy must overwrite client-supplied forwarded-protocol headers.

The disk is available only at runtime. The bootstrap runs migrations and cache creation after the volume is mounted; do not move these steps into the Docker image build or a separate pre-deploy job. SQLite and private uploads share the volume. Disk deployments briefly stop the old instance before starting the new one; data remains on the volume. Do not increase the instance count with this SQLite configuration.

After deployment, create your own teacher/student accounts. No example users or classes are created. Create an administrator from the service shell when needed:

```bash
python backend/manage.py createsuperuser
```

## Self-hosted Docker

Copy `.env.example` to `.env`, generate a random secret, and configure your exact public hostname and HTTPS origin. Put the application behind a reverse proxy which terminates TLS and overwrites `Host` and `X-Forwarded-Proto` correctly. The Compose application port is bound to `127.0.0.1`, for that proxy to access locally.

```bash
docker compose up --build -d
```

The named `academia-data` volume contains SQLite, uploads, and backup files. Keep that volume when updating or recreating containers. Do not run `docker compose down -v` on an installation whose data you need.

## Supervised startup and worker

`ops/run_server.py` prepares the mounted directory, drops privileges, locks startup, migrates the database, creates the production cache, enables SQLite WAL, collects static assets, runs Django's production checks, and launches Gunicorn plus the exam scheduler. Either child failing stops the service so the host can restart it.

The scheduler updates a database heartbeat. The health check validates the database connection, writable upload directory, and a recent heartbeat. A stale heartbeat returns HTTP 503 instead of reporting an unhealthy application as ready.

## Upgrade

Back up first, deploy the new source/image, and preserve the persistent volume. Startup applies pending migrations. Keep a backup from before a schema-changing release; rolling back code alone does not undo migrations. Existing accounts, memberships, uploads, and results remain on disk.

The earlier browser demonstration used local-only example records. Those records are not server data and are not imported. This release has removed that adapter and its sample-account shortcuts.

## Backup and recovery

Create a consistent SQLite snapshot plus every uploaded file referenced by that snapshot:

```bash
# Render service shell
python backend/manage.py backup_workspace

# Docker Compose
docker compose exec web python backend/manage.py backup_workspace
```

The command creates a private ZIP under the data directory's `backups/` folder, with a SHA-256 manifest. Copy backups off the service/volume; keeping the only backup on the same disk is not disaster recovery. If an upload is deleted during a backup, the command fails rather than silently producing an incomplete backup; retry during a quiet period.

To restore, stop the service, preserve the current data directory as a separate recovery copy, verify the backup manifest, and restore `db.sqlite3` and `media/` into an empty data directory. Set ownership to UID/GID 10001 for the supplied container, then start the service and check readiness. Never restore over a running SQLite instance.

## Limits

- The supplied host configuration is for one persistent service instance. Higher concurrency across multiple instances requires moving from SQLite and local uploads to shared database/object storage.
- Each upload is limited to 25 MB; account quotas and free-disk checks are enforced server-side. Expand the disk before it fills.
- Live video runs through the selected meeting provider; its availability and room policies apply.
- Notifications are stored in the inbox. Desktop alerts require an open page. Email/SMS/background push and email-based account recovery need a configured provider.
- Django admin is available for account support. Teacher registration remains open as requested; institutional faculty verification would need a separate approval policy.
