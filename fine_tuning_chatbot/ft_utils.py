"""Shared data loading, splitting, and per-model formatting for the study.

Everything resolves from config.yaml. Data flow:

    raw JSONL -> load_raw()           clean + dedupe
              -> load_and_split()     grouped 70/20/10 split, cached as JSONL
              -> get_formatted()      'prompt'/'completion' columns per model

Training is REPLY-ONLY: prompts carry no system instruction, and TRL computes
loss on the completion column only.
"""
import random
import re
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent

with open(ROOT / "config.yaml", encoding="utf-8") as _f:
    CFG = yaml.safe_load(_f)

SEED = CFG["seed"]
DATA_ROOT = (ROOT / CFG["paths"]["data_root"]).resolve()
MODELS_ROOT = (ROOT / CFG["paths"]["models_root"]).resolve()
RESULTS_ROOT = (ROOT / CFG["paths"]["results_root"]).resolve()
RAW_DIR = DATA_ROOT / "raw"
PROCESSED_DIR = DATA_ROOT / "processed"

_SPLITS = ("train", "val", "test")


# ---------------------------------------------------------------------------
# Load & clean
# ---------------------------------------------------------------------------
def load_raw(dataset_key, apply_filters=True):
    """Raw JSONL dump -> cleaned DataFrame with 'input'/'output' columns.
    apply_filters=False skips the quality filters (EDA inspects them itself)."""
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
    df = df.drop_duplicates(subset=["input", "output"]).reset_index(drop=True)
    return _quality_filter(df) if apply_filters else df


_PLACEHOLDER_RE = re.compile(r"\[[A-Za-z][A-Za-z '/]{0,24}\]")


def quality_filter_masks(df):
    """Per-rule boolean masks (True = row is DROPPED) from the `preprocess`
    block in config.yaml. Shared by the actual filter and the EDA notebook."""
    pcfg = CFG.get("preprocess", {})
    masks = {}
    if pcfg.get("drop_placeholder_replies"):
        masks["placeholder_reply"] = df["output"].str.contains(_PLACEHOLDER_RE)
    if pcfg.get("drop_letter_replies"):
        masks["letter_reply"] = df["output"].str.match(r"\s*Dear\b")
    max_words = pcfg.get("max_total_words")
    if max_words:
        total = df["input"].str.split().str.len() + df["output"].str.split().str.len()
        masks[f"too_long_over_{max_words}_words"] = total > max_words
    return masks


def _quality_filter(df):
    masks = quality_filter_masks(df)
    if not masks:
        return df
    drop = pd.concat(masks, axis=1).any(axis=1)
    if drop.any():
        print(f"[preprocess] quality filters dropped {drop.sum()} rows "
              f"({drop.sum() / len(df) * 100:.1f}%) -> {(~drop).sum()} kept")
    return df[~drop].reset_index(drop=True)


def add_provenance(df, dataset_key="mentalchat16k"):
    """Label each row with its source file (synthetic vs interview) via exact
    (input, output) match; unmatched rows are labeled 'unmatched'."""
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
# Split (70/20/10, grouped by user text so a question never leaks across splits)
# ---------------------------------------------------------------------------
def _grouped_split(df, ratios):
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
    df = df.sample(frac=1, random_state=SEED).reset_index(drop=True)
    n = len(df)
    t = int(n * ratios["train"])
    v = int(n * (ratios["train"] + ratios["val"]))
    return (df.iloc[:t].reset_index(drop=True),
            df.iloc[t:v].reset_index(drop=True),
            df.iloc[v:].reset_index(drop=True))


def load_and_split(dataset_key, force=False):
    """(train_df, val_df, test_df) — cached under processed/<dataset_key>/."""
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
# Per-model prompt builders — used for BOTH the training 'prompt' column and
# inference, so train and deploy always share one format. No system prompt.
# ---------------------------------------------------------------------------
def format_prompt_gemma2(input_text):
    return ("<bos><start_of_turn>user\n"
            f"{input_text}<end_of_turn>\n"
            "<start_of_turn>model\n")


def format_prompt_llama32(input_text):
    return ("<|begin_of_text|>"
            "<|start_header_id|>user<|end_header_id|>\n\n"
            f"{input_text}<|eot_id|>"
            "<|start_header_id|>assistant<|end_header_id|>\n\n")


def format_prompt_qwen3(input_text):
    # /no_think keeps Qwen3 in non-thinking mode (control token, not a prompt).
    return ("<|im_start|>system\n/no_think<|im_end|>\n"
            "<|im_start|>user\n"
            f"{input_text}<|im_end|>\n"
            "<|im_start|>assistant\n")


PROMPT_FORMATTERS = {
    "gemma2": format_prompt_gemma2,
    "llama32": format_prompt_llama32,
    "qwen3": format_prompt_qwen3,
}

# End-of-reply token per family (closes the completion during training).
END_TOKENS = {
    "gemma2": "<end_of_turn>",
    "llama32": "<|eot_id|>",
    "qwen3": "<|im_end|>",
}


# ---------------------------------------------------------------------------
# Public API for training
# ---------------------------------------------------------------------------
def get_formatted(model_key, dataset_key):
    """(train_ds, val_ds, test_ds_raw) as HF Datasets.

    train/val carry 'prompt' + 'completion' columns (TRL then computes loss on
    the completion only); test stays raw with 'input'/'output' for scoring."""
    from datasets import Dataset  # heavy import kept out of module load

    if model_key not in PROMPT_FORMATTERS:
        raise ValueError(f"Unknown model_key '{model_key}'. "
                         f"Choose from {list(PROMPT_FORMATTERS)}")

    prompt_fn = PROMPT_FORMATTERS[model_key]
    end_token = END_TOKENS[model_key]

    def to_pair(row):
        return {"prompt": prompt_fn(row["input"]),
                "completion": f"{row['output']}{end_token}"}

    train_df, val_df, test_df = load_and_split(dataset_key)
    train_ds = Dataset.from_pandas(train_df[["input", "output"]])
    val_ds = Dataset.from_pandas(val_df[["input", "output"]])
    test_ds = Dataset.from_pandas(test_df[["input", "output"]])

    return (train_ds.map(to_pair, remove_columns=train_ds.column_names),
            val_ds.map(to_pair, remove_columns=val_ds.column_names),
            test_ds)
