#!/bin/sh
# First boot: pull the weights from Hugging Face into the models volume
# (idempotent — present files are skipped, so restarts are instant).
set -e

echo "[entrypoint] checking model weights..."
python scripts/download_models.py

# ONE worker, on purpose: the rate limiter, live-claims registry, crisis-email
# cooldown and report cache are all in process memory (see README), and a
# second worker would also load a second 3.3 GB copy of the chatbot.
# --timeout covers the model load (~1-2 min on first request cycle).
echo "[entrypoint] starting gunicorn..."
exec gunicorn --workers 1 --bind 0.0.0.0:5000 --timeout 300 \
     --access-logfile - "app:create_app()"
