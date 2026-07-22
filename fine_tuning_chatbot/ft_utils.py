"""
ft_utils.py — shared data loading, splitting, and per-model chat formatting
for the fine-tuning study (3 models x 2 datasets x 2 methods).

Everything (models, datasets, paths, split ratios, crisis-example injection,
system prompt) resolves from config.yaml — nothing is hardcoded here. This
mirrors the prior mhsupportchat study's data_utils.py, extended to two
datasets, grouped splits, crisis-example injection, and Shadow-FT.

Data flow:
    raw JSONL  (data/mh_conversation/raw/)
      -> clean + dedupe                     load_raw()
      -> grouped 70/20/10 split, cached     load_and_split() -> data/.../processed/
      -> crisis examples into TRAIN only    get_split()
      -> chat-template 'text' column        get_formatted()
"""

import json
import random
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent

with open(ROOT / "config.yaml", encoding="utf-8") as _f:
    CFG = yaml.safe_load(_f)

SEED = CFG["seed"]
SYSTEM_PROMPT = CFG["system_prompt"].strip()
DATA_ROOT = (ROOT / CFG["paths"]["data_root"]).resolve()
MODELS_ROOT = (ROOT / CFG["paths"]["models_root"]).resolve()
RESULTS_ROOT = (ROOT / CFG["paths"]["results_root"]).resolve()
RAW_DIR = DATA_ROOT / "raw"
PROCESSED_DIR = DATA_ROOT / "processed"

_SPLITS = ("train", "val", "test")


# ---------------------------------------------------------------------------
# Load & clean
# ---------------------------------------------------------------------------

def load_raw(dataset_key):
    """Raw JSONL dump -> cleaned DataFrame with 'input'/'output' columns.

    Cleaning follows the prior study: strip whitespace, drop empty rows,
    drop exact (input, output) duplicates. Field names come from the
    dataset's schema block in config.yaml.
    """
    dcfg = CFG["datasets"][dataset_key]
    schema = dcfg["schema"]
    df = pd.read_json(RAW_DIR / dcfg["raw_filename"], lines=True)

    user_field = schema.get("user_field", schema.get("input_field"))
    out_field = schema.get("assistant_field", schema.get("output_field"))
    df = df.rename(columns={user_field: "input", out_field: "output"})

    if dcfg.get("use_instruction_field") and schema.get("instruction_field"):
        instr = df[schema["instruction_field"]].fillna("").astype(str).str.strip()
        df["input"] = (instr + "\n\n" + df["input"].fillna("").astype(str)).str.strip()

    df = df[["input", "output"]].copy()
    for col in ("input", "output"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    df = df[df["input"].ne("") & df["output"].ne("")]
    return df.drop_duplicates(subset=["input", "output"]).reset_index(drop=True)


def add_provenance(df, dataset_key="mentalchat16k"):
    """Label each row with its source file via exact (input, output) match.

    Iterates config's source_files in order, so on the rare key present in
    more than one source the LAST listed file wins. Rows matching no source
    are labeled 'unmatched'.
    """
    src_files = CFG["datasets"][dataset_key].get("source_files", {})
    key = df["input"] + "\x00" + df["output"]
    df = df.copy()
    df["source"] = "unmatched"
    for name, filename in src_files.items():
        sdf = pd.read_csv(RAW_DIR / filename)
        skey = (sdf["input"].fillna("").astype(str).str.strip() + "\x00"
                + sdf["output"].fillna("").astype(str).str.strip())
        df.loc[key.isin(set(skey)), "source"] = name
    return df


# ---------------------------------------------------------------------------
# Split (70/20/10, seed from config, grouped by user text when configured)
# ---------------------------------------------------------------------------

def _grouped_split(df, ratios):
    """Assign whole groups of identical user text to one split, so the same
    question never leaks across train/val/test."""
    rng = random.Random(SEED)
    groups = list(df.groupby("input", sort=True).groups.items())
    rng.shuffle(groups)

    n = len(df)
    train_cut = ratios["train"] * n
    val_cut = (ratios["train"] + ratios["val"]) * n
    idx = {"train": [], "val": [], "test": []}
    seen = 0
    for _, rows in groups:
        if seen < train_cut:
            idx["train"].extend(rows)
        elif seen < val_cut:
            idx["val"].extend(rows)
        else:
            idx["test"].extend(rows)
        seen += len(rows)
    return tuple(
        df.loc[idx[s]].sample(frac=1, random_state=SEED).reset_index(drop=True)
        for s in _SPLITS
    )


def _row_split(df, ratios):
    """Plain row-level shuffle + slice (the prior study's method)."""
    df = df.sample(frac=1, random_state=SEED).reset_index(drop=True)
    n = len(df)
    t = int(n * ratios["train"])
    v = int(n * (ratios["train"] + ratios["val"]))
    return (df.iloc[:t].reset_index(drop=True),
            df.iloc[t:v].reset_index(drop=True),
            df.iloc[v:].reset_index(drop=True))


def load_and_split(dataset_key, force=False):
    """Return (train_df, val_df, test_df); cached as JSONL under
    data/mh_conversation/processed/<dataset_key>/. Crisis examples are NOT
    in these files — they are injected at get_split() time, train only."""
    out_dir = PROCESSED_DIR / dataset_key
    paths = {s: out_dir / f"{s}.jsonl" for s in _SPLITS}
    if not force and all(p.exists() for p in paths.values()):
        return tuple(pd.read_json(paths[s], lines=True) for s in _SPLITS)

    df = load_raw(dataset_key)
    ratios = CFG["split"]["ratios"]
    if CFG["datasets"][dataset_key].get("group_split_by_user_text"):
        splits = _grouped_split(df, ratios)
    else:
        splits = _row_split(df, ratios)

    out_dir.mkdir(parents=True, exist_ok=True)
    for s, part in zip(_SPLITS, splits):
        part.to_json(paths[s], orient="records", lines=True, force_ascii=False)
    print(f"[{dataset_key}] saved splits -> {out_dir} "
          f"(train {len(splits[0])}, val {len(splits[1])}, test {len(splits[2])})")
    return splits


# ---------------------------------------------------------------------------
# Crisis-example injection (train split only)
# ---------------------------------------------------------------------------

def load_crisis_examples():
    with open(ROOT / CFG["crisis_examples"]["file"], encoding="utf-8") as f:
        return json.load(f)


def get_split(dataset_key, inject_crisis=None):
    """Splits ready for training. Per config, the curated crisis examples are
    appended to TRAIN only (n_copies each) and the train split reshuffled;
    val/test never contain them."""
    train_df, val_df, test_df = load_and_split(dataset_key)
    ccfg = CFG["crisis_examples"]
    if inject_crisis is None:
        inject_crisis = ccfg.get("inject", False)
    if inject_crisis:
        extra = pd.DataFrame(load_crisis_examples() * ccfg.get("n_copies", 1))
        train_df = (
            pd.concat([train_df[["input", "output"]], extra[["input", "output"]]],
                      ignore_index=True)
            .sample(frac=1, random_state=SEED)
            .reset_index(drop=True)
        )
    return train_df, val_df, test_df


# ---------------------------------------------------------------------------
# Per-model chat-template formatters (manual templates, as in the prior study)
# ---------------------------------------------------------------------------

def _user_text(model_key, input_text):
    """Fold the system prompt into the user turn for models whose chat
    template rejects a system role (Gemma 2, per config)."""
    if CFG["models"][model_key].get("supports_system_role", True):
        return input_text
    return f"{SYSTEM_PROMPT}\n\n{input_text}"


def _format_gemma2(row):
    return {"text": (
        "<bos><start_of_turn>user\n"
        f"{_user_text('gemma2', row['input'])}<end_of_turn>\n"
        "<start_of_turn>model\n"
        f"{row['output']}<end_of_turn>"
    )}


def _format_llama32(row):
    return {"text": (
        "<|begin_of_text|>"
        "<|start_header_id|>system<|end_header_id|>\n\n"
        f"{SYSTEM_PROMPT}<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\n"
        f"{row['input']}<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n"
        f"{row['output']}<|eot_id|>"
    )}


def _format_qwen3(row):
    # /no_think keeps Qwen3 in non-thinking mode (see config note).
    return {"text": (
        "<|im_start|>system\n"
        f"/no_think\n{SYSTEM_PROMPT}<|im_end|>\n"
        "<|im_start|>user\n"
        f"{row['input']}<|im_end|>\n"
        "<|im_start|>assistant\n"
        f"{row['output']}<|im_end|>"
    )}


_FORMATTERS = {
    "gemma2": _format_gemma2,
    "llama32": _format_llama32,
    "qwen3": _format_qwen3,
}


# Prompt-only formatters (inference — no output/label).

def format_prompt_gemma2(input_text):
    return (
        "<bos><start_of_turn>user\n"
        f"{_user_text('gemma2', input_text)}<end_of_turn>\n"
        "<start_of_turn>model\n"
    )


def format_prompt_llama32(input_text):
    return (
        "<|begin_of_text|>"
        "<|start_header_id|>system<|end_header_id|>\n\n"
        f"{SYSTEM_PROMPT}<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\n"
        f"{input_text}<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def format_prompt_qwen3(input_text):
    return (
        "<|im_start|>system\n"
        f"/no_think\n{SYSTEM_PROMPT}<|im_end|>\n"
        "<|im_start|>user\n"
        f"{input_text}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


PROMPT_FORMATTERS = {
    "gemma2": format_prompt_gemma2,
    "llama32": format_prompt_llama32,
    "qwen3": format_prompt_qwen3,
}


# ---------------------------------------------------------------------------
# Public API for the train notebook
# ---------------------------------------------------------------------------

def get_formatted(model_key, dataset_key):
    """Returns (train_ds, val_ds, test_ds_raw) as HF Datasets.
    train/val carry a 'text' column with the model's chat template applied
    (crisis examples included in train per config); test stays raw with
    'input'/'output' columns for metric scoring."""
    from datasets import Dataset  # heavy import kept out of module load

    if model_key not in _FORMATTERS:
        raise ValueError(f"Unknown model_key '{model_key}'. Choose from {list(_FORMATTERS)}")

    train_df, val_df, test_df = get_split(dataset_key)
    formatter = _FORMATTERS[model_key]

    train_ds = Dataset.from_pandas(train_df[["input", "output"]])
    val_ds = Dataset.from_pandas(val_df[["input", "output"]])
    test_ds = Dataset.from_pandas(test_df[["input", "output"]])

    train_fmt = train_ds.map(formatter, remove_columns=train_ds.column_names)
    val_fmt = val_ds.map(formatter, remove_columns=val_ds.column_names)
    return train_fmt, val_fmt, test_ds
