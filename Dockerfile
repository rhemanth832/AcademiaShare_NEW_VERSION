FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.js ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM python:3.12-slim AS python-deps
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_ENV=production \
    DJANGO_DEBUG=0 \
    ACADEMIA_DATA_DIR=/var/data \
    ACADEMIA_SCHEDULER_REQUIRED=1 \
    ACADEMIA_DROP_PRIVILEGES=1
WORKDIR /app
RUN groupadd --gid 10001 academia && useradd --uid 10001 --gid academia --no-create-home academia
COPY --from=python-deps /install /usr/local
COPY --from=frontend /build/dist ./dist
COPY backend ./backend
COPY ops ./ops
COPY public/favicon.svg ./public/favicon.svg
RUN mkdir -p /var/data /app/backend/staticfiles && chown -R 10001:10001 /app/backend/staticfiles /var/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD python -c "import os,urllib.request; r=urllib.request.Request('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health/',headers={'X-Forwarded-Proto':'https'}); urllib.request.urlopen(r,timeout=4)"
# The bootstrap prepares a new volume, then drops root before application startup.
CMD ["python", "ops/run_server.py"]
