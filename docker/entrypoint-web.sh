#!/bin/sh
# Web-tier entrypoint: no weight download — straight to gunicorn.
#
# ONE worker on purpose: the rate limiter, live-claims registry, crisis-email
# cooldown and report cache are in process memory (see README).
# --timeout 330 > RUNPOD_TIMEOUT_S (300): a chat request may legitimately hold
# the connection through a full RunPod cold start; gunicorn's default 30 s
# would kill it mid-wait.
# ${PORT:-5000}: PaaS hosts (Render/Railway/Fly) inject PORT; default 5000.
set -e
exec gunicorn --workers 1 --bind "0.0.0.0:${PORT:-5000}" --timeout 330 \
     --access-logfile - "app:create_app()"
