# MindMate — GPU deployment image.
#
#   docker compose up --build          (see docker-compose.yml; needs the
#                                       NVIDIA container toolkit on the host)
#
# python-slim + the cu124 torch wheel (bundles the CUDA runtime; the host only
# provides the driver) — the same install pattern the README documents. Weights
# are NOT baked in: the entrypoint downloads them from Hugging Face (Fz0212)
# into the /app/models volume on first boot (~9.5 GB), so the image stays small
# and rebuilds don't re-download.
FROM python:3.12-slim

WORKDIR /app

# torch first (biggest layer, changes least), then the app deps.
# cu128, not cu124: Blackwell GPUs (RTX 50xx, sm_120) need CUDA >= 12.8 kernels,
# and the cu128 wheel still covers the older datacenter/consumer archs.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu128
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The app. .dockerignore keeps models/, data/, the study, and .env out.
COPY app ./app
COPY scripts ./scripts
COPY config.yaml run.py schema.sql ./

# Non-secret defaults — everything secret (Supabase keys, SMTP, SECRET_KEY)
# arrives at runtime via --env-file / compose `env_file`, never in the image.
# HF_HOME inside /app/models puts the summarizer (an HF hub id, downloaded at
# first load rather than by download_models.py) into the models VOLUME — so a
# recreated container doesn't re-download ~3 GB.
ENV AI_MODE=real \
    CLASSIFIER_PATH=models/classifier_models/roberta_onnx_int8 \
    CHAT_MODEL_PATH=models/chat_models/mentalchat16k/qwen3_merged \
    CHAT_MODEL_FAMILY=qwen3 \
    HF_HOME=/app/models/.hf_cache \
    PYTHONUNBUFFERED=1

EXPOSE 5000

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
