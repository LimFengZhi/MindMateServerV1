#!/bin/sh
# RunPod serverless entrypoint. All weights are baked into the image, so this
# check is an instant no-op safety net (it would only download if a bake step
# was skipped or a layer is broken).
set -e

echo "[entrypoint] verifying baked model weights..."
python scripts/download_models.py

echo "[entrypoint] starting RunPod serverless handler..."
exec python scripts/runpod_handler.py
