"""Download the deployment models from Hugging Face (Fz0212) into the models/
layout the app's Config defaults expect.

    python scripts/download_models.py            # download whatever is missing
    python scripts/download_models.py --check    # report only, download nothing
    python scripts/download_models.py --only qwen3 classifier

Idempotent: a repo is skipped when its target folder already holds a weights
file, so this is safe as a container entrypoint step (first boot downloads into
the models volume, ~9.5 GB; every later boot is instant). `models/` is
gitignored — this script is how a fresh clone or a fresh container gets its
weights.

The classifier is the ONNX int8 export (125 MB, CPU-fast). Point .env at it:
    CLASSIFIER_PATH=models/classifier_models/roberta_onnx_int8
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# key -> (HF repo, target dir relative to the repo root, a file that proves
#         the weights are present)
MODELS = {
    "qwen3": ("Fz0212/mindmate-qwen3-1.7b-mentalchat16k",
              "models/chat_models/mentalchat16k/qwen3_merged",
              "model.safetensors"),
    "gemma2": ("Fz0212/mindmate-gemma2-2b-mentalchat16k",
               "models/chat_models/mentalchat16k/gemma2_merged",
               "model.safetensors"),
    "llama32": ("Fz0212/mindmate-llama32-1b-mentalchat16k",
                "models/chat_models/mentalchat16k/llama32_merged",
                "model.safetensors"),
    "classifier": ("Fz0212/mh-roberta-classifier-onnx-int8",
                   "models/classifier_models/roberta_onnx_int8",
                   "model_quantized.onnx"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="report what is present/missing, download nothing")
    ap.add_argument("--only", nargs="+", choices=sorted(MODELS),
                    help="restrict to these keys (default: all)")
    ap.add_argument("--force", action="store_true",
                    help="re-download even if the weights file exists")
    args = ap.parse_args()

    keys = args.only or list(MODELS)
    missing = []
    for key in keys:
        repo, rel, marker = MODELS[key]
        target = ROOT / rel
        present = (target / marker).exists()
        state = "present" if present and not args.force else "MISSING"
        print(f"{key:10} {state:8} {rel}   ({repo})")
        if not present or args.force:
            missing.append(key)

    if args.check:
        sys.exit(1 if missing else 0)
    if not missing:
        print("\nnothing to download.")
        return

    from huggingface_hub import snapshot_download  # deferred: --check needs no hub
    for key in missing:
        repo, rel, _ = MODELS[key]
        target = ROOT / rel
        target.mkdir(parents=True, exist_ok=True)
        print(f"\n[download] {repo} -> {rel}")
        snapshot_download(repo_id=repo, local_dir=str(target))
    print("\ndone.")


if __name__ == "__main__":
    main()
