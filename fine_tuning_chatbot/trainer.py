"""Reusable QLoRA training routine — one call per (model, dataset) run.

    import trainer
    info = trainer.train("gemma2")                       # full run
    info = trainer.train("gemma2", max_steps=2, ...)     # quick smoke run

All hyperparameters come from config.yaml; keyword overrides go straight into
SFTConfig (e.g. max_steps, eval_strategy). Loss is computed on the completion
column only (reply-only training).
"""
import gc
import json
import time
from pathlib import Path

import ft_utils


def train(model_key, dataset_key="mentalchat16k", out_dir=None, **sft_overrides):
    """Run one QLoRA fine-tune and return the run manifest dict."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, TaskType, get_peft_model
    from trl import SFTTrainer, SFTConfig

    mcfg = ft_utils.CFG["models"][model_key]
    tcfg = ft_utils.CFG["training"]
    qcfg, lcfg = tcfg["quant"], tcfg["lora"]
    model_id = mcfg["instruct_id"]
    run_name = f"{model_key}_{dataset_key}"
    adapter_out = Path(out_dir) if out_dir else \
        ft_utils.MODELS_ROOT / dataset_key / model_key

    print(f"=== RUN {run_name} — {ft_utils.CFG['datasets'][dataset_key]['name']} ===")

    # Data: prompt/completion pairs (loss on completion only)
    train_ds, val_ds, test_ds_raw = ft_utils.get_formatted(model_key, dataset_key)
    print(f"Train {len(train_ds)} | Val {len(val_ds)} | Test {len(test_ds_raw)}")
    print(f"Sample prompt:     {train_ds[0]['prompt'][:150]!r}")
    print(f"Sample completion: {train_ds[0]['completion'][:150]!r}")

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.padding_side = "right"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs = dict(
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
        model_kwargs["attn_implementation"] = mcfg["attn_implementation"]

    model = AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(
        r=lcfg["r"], lora_alpha=lcfg["alpha"], lora_dropout=lcfg["dropout"],
        bias="none", target_modules=list(lcfg["target_modules"]),
        task_type=TaskType.CAUSAL_LM,
    ))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Trainable params: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)")

    sft_kwargs = {k: v for k, v in tcfg.items()
                  if k not in ("lora", "quant", "max_seq_length")}
    sft_kwargs.update(sft_overrides)
    sft_config = SFTConfig(
        output_dir=str(ft_utils.ROOT / "checkpoints" / run_name),
        max_length=tcfg["max_seq_length"],
        completion_only_loss=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        **sft_kwargs,
    )
    sft_trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        args=sft_config,
    )

    start = time.time()
    sft_trainer.train()
    minutes = (time.time() - start) / 60
    print(f"Training complete in {minutes:.1f} minutes")

    adapter_out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(adapter_out)
    tokenizer.save_pretrained(adapter_out)
    manifest = {
        "run_name": run_name,
        "model_key": model_key,
        "family": mcfg["family"],
        "dataset_key": dataset_key,
        "method": "qlora-completion-only",
        "model_id": model_id,
        "seed": ft_utils.SEED,
        "max_seq_length": tcfg["max_seq_length"],
        "learning_rate": tcfg["learning_rate"],
        "train_minutes": round(minutes, 1),
        "final_train_loss": next((h["train_loss"] for h in
                                  reversed(sft_trainer.state.log_history)
                                  if "train_loss" in h), None),
        "best_eval_loss": min((h["eval_loss"] for h in sft_trainer.state.log_history
                               if "eval_loss" in h), default=None),
    }
    with open(adapter_out / "run_info.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Saved adapter + run_info.json -> {adapter_out}")

    _smoke_test(model, tokenizer, model_key, test_ds_raw)

    del sft_trainer, model
    gc.collect()
    torch.cuda.empty_cache()
    return manifest


def _smoke_test(model, tokenizer, model_key, test_ds_raw, n=2):
    """Greedy generations on held-out prompts, printed for a quick eyeball."""
    import torch
    model.eval()
    model.config.use_cache = True
    prompt_fn = ft_utils.PROMPT_FORMATTERS[model_key]
    for idx in range(n):
        user_input = test_ds_raw[idx]["input"]
        # add_special_tokens=False: the template string already carries BOS
        inputs = tokenizer(prompt_fn(user_input), return_tensors="pt",
                           add_special_tokens=False).to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=200, do_sample=False)
        reply = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:],
                                 skip_special_tokens=True)
        print(f"\n--- Sample {idx + 1} ---")
        print(f"USER:  {user_input[:200]}")
        print(f"MODEL: {reply[:400]}")
