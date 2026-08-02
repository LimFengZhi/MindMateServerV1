"""Shared evaluation layer: generate each system's responses on THE test set
(mentalchat16k held-out split) once, store them, and let both evaluation
notebooks consume the same stored files.

    import evaluator
    evaluator.generate_and_store("gemma2", "tuned")   # cached jsonl, skip if exists
    recs = evaluator.load_generations("gemma2", "tuned")
    bed  = evaluator.testbed()                        # grouped questions + refs

Storage: results/generations/<model>_<variant>.jsonl
         one line per unique test question: {"input", "refs", "prediction"}
Variants: "tuned" (instruct + this study's adapter) | "base" (instruct as-is).
"""
import gc
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # ft root (ft_utils, config)
import ft_utils

GEN_DIR = ft_utils.RESULTS_ROOT / "generations"
DATASET_KEY = "mentalchat16k"

# Markers that end an assistant turn, and markers that start a new one (base
# models often keep "chatting" — cut there too).
_END_MARKERS = ["<end_of_turn>", "<|eot_id|>", "<|im_end|>",
                "<|endoftext|>", "<|end_of_text|>", "<eos>"]
_TURN_MARKERS = ["<start_of_turn>", "<|start_header_id|>", "<|im_start|>", "<bos>"]
_LEFTOVER_TOKENS = _END_MARKERS + _TURN_MARKERS + ["/no_think"]


def clean_output(text):
    """Cut the decoded continuation at the first end/new-turn marker, strip
    leftover template tokens and Qwen <think> blocks."""
    for marker in _END_MARKERS + _TURN_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    for tok in _LEFTOVER_TOKENS:
        text = text.replace(tok, "")
    return text.strip()


def _stop_token_ids(tokenizer, model_key):
    end_tok = {"gemma2": "<end_of_turn>", "llama32": "<|eot_id|>",
               "qwen3": "<|im_end|>"}[model_key]
    ids = {tokenizer.eos_token_id}
    tid = tokenizer.convert_tokens_to_ids(end_tok)
    if tid is not None and tid >= 0:
        ids.add(tid)
    return [i for i in ids if i is not None]


def testbed(dataset_key=DATASET_KEY):
    """Unique test questions with ALL their reference answers (a handful of
    inputs repeat with different outputs; scoring is multi-reference)."""
    _, _, test_df = ft_utils.load_and_split(dataset_key)
    return (test_df.groupby("input", sort=True)["output"].apply(list)
            .reset_index().rename(columns={"output": "refs"}))


def load_system(model_key, variant):
    """4-bit instruct model; 'tuned' attaches this study's LoRA adapter."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    mcfg = ft_utils.CFG["models"][model_key]
    qcfg = ft_utils.CFG["training"]["quant"]
    kwargs = dict(
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=qcfg["load_in_4bit"],
            bnb_4bit_quant_type=qcfg["bnb_4bit_quant_type"],
            bnb_4bit_compute_dtype=getattr(torch, qcfg["bnb_4bit_compute_dtype"]),
            bnb_4bit_use_double_quant=qcfg["bnb_4bit_use_double_quant"],
        ),
        device_map="auto",
        dtype=torch.bfloat16,
    )
    if mcfg.get("attn_implementation"):
        kwargs["attn_implementation"] = mcfg["attn_implementation"]

    model = AutoModelForCausalLM.from_pretrained(mcfg["instruct_id"], **kwargs)
    if variant == "tuned":
        adapter = ft_utils.MODELS_ROOT / DATASET_KEY / model_key
        model = PeftModel.from_pretrained(model, str(adapter))
        tokenizer = AutoTokenizer.from_pretrained(str(adapter))
    else:
        tokenizer = AutoTokenizer.from_pretrained(mcfg["instruct_id"])
    model.eval()
    model.config.use_cache = True
    return model, tokenizer


def generate_predictions(model, tokenizer, inputs_list, model_key,
                         max_new_tokens=200, batch_size=8):
    """Batched greedy generation. Decodes WITHOUT skipping special tokens so
    clean_output can cut at the first end-of-turn marker."""
    import torch

    model.eval()
    tokenizer.padding_side = "left"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    prompt_fn = ft_utils.PROMPT_FORMATTERS[model_key]
    stop_ids = _stop_token_ids(tokenizer, model_key)
    max_len = ft_utils.CFG["training"]["max_seq_length"]
    predictions = []
    for i in range(0, len(inputs_list), batch_size):
        prompts = [prompt_fn(x) for x in inputs_list[i:i + batch_size]]
        # add_special_tokens=False: the templates already carry BOS
        encoded = tokenizer(prompts, return_tensors="pt", padding=True,
                            truncation=True, max_length=max_len,
                            add_special_tokens=False).to(model.device)
        with torch.no_grad():
            output_ids = model.generate(
                **encoded,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                eos_token_id=stop_ids,
                pad_token_id=tokenizer.pad_token_id,
            )
        prompt_len = encoded["input_ids"].shape[1]
        for out in output_ids:
            decoded = tokenizer.decode(out[prompt_len:], skip_special_tokens=False)
            predictions.append(clean_output(decoded))
        print(f"    {min(i + batch_size, len(inputs_list))}/{len(inputs_list)}", end="\r")
    print(f"    {len(inputs_list)}/{len(inputs_list)} done")
    return predictions


def generation_path(model_key, variant):
    return GEN_DIR / f"{model_key}_{variant}.jsonl"


def adapter_available(model_key):
    return (ft_utils.MODELS_ROOT / DATASET_KEY / model_key /
            "adapter_config.json").exists()


def generate_and_store(model_key, variant, force=False):
    """One generation pass over the test set -> cached jsonl. Returns the path
    (None if the tuned adapter doesn't exist yet). Frees VRAM afterwards."""
    import torch

    path = generation_path(model_key, variant)
    if path.exists() and not force:
        print(f"[cached]  {path.name}")
        return path
    if variant == "tuned" and not adapter_available(model_key):
        print(f"[skipped] {path.name} — adapter not trained yet")
        return None

    print(f"[running] {path.name}")
    start = time.time()
    bed = testbed()
    model, tokenizer = load_system(model_key, variant)
    preds = generate_predictions(model, tokenizer, bed["input"].tolist(), model_key)

    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()

    GEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for (_, row), pred in zip(bed.iterrows(), preds):
            f.write(json.dumps({"input": row["input"], "refs": row["refs"],
                                "prediction": pred}, ensure_ascii=False) + "\n")
    print(f"          done in {(time.time() - start) / 60:.1f} min -> {path.name}")
    return path


def load_generations(model_key, variant):
    """Stored records for one system, or None if not generated yet."""
    path = generation_path(model_key, variant)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]
