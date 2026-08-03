"""Single-agent vs multi-agent pipeline evaluation on MULTI-TURN counseling
conversations (Jingy2000/multi-turn-counsel-chat — CounselChat Q&A expanded to
client/counselor dialogues with GPT-4).

n_cases conversations (seeded) are replayed TEACHER-FORCED: at every client
turn, each system answers given the dataset's own conversation so far, so
both systems and every turn share identical context. The SAME tuned gemma2
answers in both arms — only the app's architecture differs:

    pipeline_single  the app's 'single' prompt + the VERBATIM history as
                     alternating chat turns (the Test Chat bench's
                     single-agent baseline, offline).
    pipeline_multi   the app pipeline per turn: RoBERTa diagnosis -> crisis
                     routing (escalated turns get the app's fixed crisis
                     message, like the graph's route_turn); the rest generate
                     with the app's memory design read from the root
                     config.yaml — the last `memory.recent_turns` exchanges
                     VERBATIM, everything older compressed into
                     {summarised_history} by the APP'S summarizer model
                     (mirrors nodes.load_context/summarize exactly, including
                     the first-turn and just-begun summary wordings).

Replies are scored on the SoulChat CEHS rubric (Table 2, arXiv:2311.00273):
Content 0-2 · Empathy 0-2 · Helpfulness 0-2 · Safety 0-1, judged by the same
GLM judge the other evaluation uses (llm_judge.make_client), rubric text in
cehs_prompt.txt.

Prompts, thresholds, the crisis message/regex, and the summarizer identity
are all read FROM the app (prompt .txt files, root config.yaml + .env,
guards.py by file path), so the evaluation can't drift from deployment.

Storage: results/generations/pipeline_<single|multi>.jsonl — one line per
(case, client turn); CEHS verdicts append to
results/single_vs_multi/cehs_raw.jsonl (resume-safe, like judge_many).
"""
import gc
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # ft root
import ft_utils
import evaluator
import llm_judge

APP_ROOT = ft_utils.ROOT.parent                       # the Flask app repo root
APP_PROMPT_DIR = APP_ROOT / "app" / "agents" / "prompt"
CLASSIFIER_DIR = APP_ROOT / "models" / "classifier_models" / "roberta"
HERE = Path(__file__).resolve().parent

# The app's tuning values — same sources the live pipeline reads via Config.
with open(APP_ROOT / "config.yaml", encoding="utf-8") as _f:
    _APP_CFG = yaml.safe_load(_f) or {}
RISK_CLASS = (_APP_CFG.get("risk") or {}).get("class", "Suicidal")
RISK_THRESHOLD = float((_APP_CFG.get("risk") or {}).get("escalation_threshold", 0.8))
CRISIS_MESSAGE = (_APP_CFG.get("crisis_message") or "").strip()
SUMMARIZER_MAX_NEW_TOKENS = int((_APP_CFG.get("summarizer") or {})
                                .get("max_new_tokens", 50))

RECENT_TURNS = int((_APP_CFG.get("memory") or {}).get("recent_turns", 0))

SVM_CFG = ft_utils.CFG.get("single_vs_multi", {})
N_CASES = int(SVM_CFG.get("n_cases", 10))
MAX_CLIENT_TURNS = int(SVM_CFG.get("max_client_turns", 6))
RAW_PATH = ft_utils.RAW_DIR / SVM_CFG.get("raw_filename", "multiturn_counselchat.json")
HF_ID = SVM_CFG.get("hf_id", "Jingy2000/multi-turn-counsel-chat")

# Summary wordings, matching app/agents/nodes.py summarize().
FIRST_TURN_SUMMARY = ("This is the user's first message — the conversation is "
                      "just beginning.")
JUST_BEGUN_SUMMARY = ("The conversation has only just begun (a few messages "
                      "so far).")


def _app_env(name, default=""):
    """One value from the app's .env (no dotenv dependency needed here)."""
    env_path = APP_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip() or default
    return default


SUMMARIZER_ID = _app_env("SUMMARIZER_PATH", "Qwen/Qwen2.5-0.5B-Instruct")


def _load_guards():
    """app/agents/guards.py by file path (it imports only `re`) — the crisis
    regex is THE app's, never a copy that could drift."""
    spec = importlib.util.spec_from_file_location(
        "app_guards", APP_ROOT / "app" / "agents" / "guards.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guards = _load_guards()


# ---------------------------------------------------------------------------
# Prompts (the bundled .txt files = the DB prompts' seed/fallback text)
# ---------------------------------------------------------------------------
def _prompt_text(filename):
    return (APP_PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


def single_system_text():
    return _prompt_text("single_prompt.txt")


def composed_system_text(summary):
    return (_prompt_text("composed_prompt.txt")
            .replace("{diagnostic_label}", "Unknown")
            .replace("{summarised_history}", summary or FIRST_TURN_SUMMARY))


def gemma_chat_prompt(system_text, history, message):
    """Gemma 2 chat template (no system role — the system text folds into the
    first user turn, like the app's LocalChatModel fold_system=True), with the
    (client, counselor) history as alternating user/model turns."""
    parts = ["<bos>"]
    first_user = f"{system_text}\n\n{history[0][0]}" if history else \
                 f"{system_text}\n\n{message}"
    if history:
        parts.append(f"<start_of_turn>user\n{first_user}<end_of_turn>\n")
        parts.append(f"<start_of_turn>model\n{history[0][1]}<end_of_turn>\n")
        for client_msg, counselor_msg in history[1:]:
            parts.append(f"<start_of_turn>user\n{client_msg}<end_of_turn>\n")
            parts.append(f"<start_of_turn>model\n{counselor_msg}<end_of_turn>\n")
        parts.append(f"<start_of_turn>user\n{message}<end_of_turn>\n")
    else:
        parts.append(f"<start_of_turn>user\n{first_user}<end_of_turn>\n")
    parts.append("<start_of_turn>model\n")
    return "".join(parts)


def format_history(history):
    """[(client, counselor)] -> the transcript text the summarizer reads
    (same shape as app/agents/prompts.py format_history)."""
    lines = []
    for client_msg, counselor_msg in history:
        lines.append(f"User: {client_msg}")
        lines.append(f"Companion: {counselor_msg}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cases: seeded conversations, replayed teacher-forced
# ---------------------------------------------------------------------------
def load_cases():
    """n_cases seeded conversations -> replay tasks. The dataset's leading
    counselor greeting is dropped (the app has no bot-first turn; the
    frontend welcome bubble is never part of the pipeline), leaving clean
    (client, counselor) exchange pairs.

    Returns a list of cases: {"case": i, "turns": [{"turn", "history"
    [(client, counselor), ...], "message", "reference"}, ...]}."""
    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"{RAW_PATH} missing — download it once with:\n"
            f"  curl -L https://huggingface.co/datasets/{HF_ID}/resolve/main/"
            f"all_dialogue_cleaned.json -o \"{RAW_PATH}\"")
    data = json.loads(RAW_PATH.read_text(encoding="utf-8"))

    rng = random.Random(ft_utils.SEED)
    picked = sorted(rng.sample(range(len(data)), min(N_CASES, len(data))))

    cases = []
    for case_id in picked:
        msgs = data[case_id]["messages"]
        if msgs and msgs[0]["role"] == "counselor":
            msgs = msgs[1:]                       # drop the greeting
        # pair up client -> counselor exchanges
        pairs = []
        i = 0
        while i + 1 < len(msgs):
            if msgs[i]["role"] == "client" and msgs[i + 1]["role"] == "counselor":
                pairs.append((msgs[i]["content"], msgs[i + 1]["content"]))
                i += 2
            else:                                 # malformed alternation
                i += 1
        turns = [{"turn": t,
                  "history": pairs[:t],
                  "message": client_msg,
                  "reference": counselor_msg}
                 for t, (client_msg, counselor_msg)
                 in enumerate(pairs[:MAX_CLIENT_TURNS])]
        cases.append({"case": case_id, "turns": turns})
    return cases


def flat_turns(cases):
    return [(c["case"], t) for c in cases for t in c["turns"]]


# ---------------------------------------------------------------------------
# App components run offline: diagnosis + summarizer memory
# ---------------------------------------------------------------------------
def classifier_available():
    return (CLASSIFIER_DIR / "config.json").exists()


def diagnose_all(messages, batch_size=32):
    """RoBERTa emotion classification with the app's escalation rule — the
    same fields the pipeline's diagnose node produces."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(CLASSIFIER_DIR))
    model = AutoModelForSequenceClassification.from_pretrained(str(CLASSIFIER_DIR))
    model.eval()
    risk_id = model.config.label2id.get(RISK_CLASS)

    out = []
    for i in range(0, len(messages), batch_size):
        batch = messages[i:i + batch_size]
        enc = tok(batch, return_tensors="pt", padding=True,
                  truncation=True, max_length=512)
        with torch.inference_mode():
            probs = torch.softmax(model(**enc).logits, dim=-1)
        for text, p in zip(batch, probs):
            top = int(p.argmax())
            risk_conf = float(p[risk_id]) if risk_id is not None else 0.0
            out.append({
                "emotion": model.config.id2label[top],
                "confidence": round(float(p[top]), 4),
                "risk_confidence": round(risk_conf, 4),
                "escalated": bool(risk_conf >= RISK_THRESHOLD
                                  or guards.crisis_keywords_present(text)),
            })
    del model, tok
    gc.collect()
    return out


def summarize_all(olders, fulls):
    """The APP's summarizer (SUMMARIZER_PATH weights + summarise_prompt.txt)
    over each turn's OLDER history (the part outside the verbatim window).
    Wordings mirror nodes.summarize: no history at all -> first-turn text;
    history exists but none is old enough to summarize -> just-begun text."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    todo_idx = [i for i, older in enumerate(olders) if older]
    summaries = [FIRST_TURN_SUMMARY if not full else JUST_BEGUN_SUMMARY
                 for full in fulls]
    if not todo_idx:
        return summaries

    tok = AutoTokenizer.from_pretrained(SUMMARIZER_ID)
    model = AutoModelForCausalLM.from_pretrained(
        SUMMARIZER_ID, dtype=torch.bfloat16, device_map="auto")
    model.eval()

    system_text = _prompt_text("summarise_prompt.txt")
    for i in todo_idx:
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user",
             "content": f"CONVERSATION:\n{format_history(olders[i])}"},
        ]
        prompt = tok.apply_chat_template(messages, tokenize=False,
                                         add_generation_prompt=True)
        enc = tok(prompt, return_tensors="pt",
                  add_special_tokens=False).to(model.device)
        with torch.no_grad():
            out_ids = model.generate(**enc,
                                     max_new_tokens=SUMMARIZER_MAX_NEW_TOKENS,
                                     do_sample=False,
                                     pad_token_id=tok.pad_token_id
                                     or tok.eos_token_id)
        text = tok.decode(out_ids[0][enc["input_ids"].shape[1]:],
                          skip_special_tokens=True).strip()
        summaries[i] = text or summaries[i]

    del model, tok
    gc.collect()
    torch.cuda.empty_cache()
    return summaries


# ---------------------------------------------------------------------------
# Generation (cached like evaluator's passes)
# ---------------------------------------------------------------------------
SYSTEMS = ("pipeline_single", "pipeline_multi")
GEN_MAX_LENGTH = 4096       # multi-turn single-agent prompts exceed the 1024
                            # training window; gemma2 handles this easily


def generation_path(system):
    return evaluator.GEN_DIR / f"{system}.jsonl"


def load_generations(system):
    path = generation_path(system)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def generate_and_store(system, force=False):
    """One replay pass for 'pipeline_single' or 'pipeline_multi' -> cached
    jsonl (one line per case x client turn)."""
    import torch

    assert system in SYSTEMS, f"unknown system '{system}'"
    path = generation_path(system)
    if path.exists() and not force:
        print(f"[cached]  {path.name}")
        return path
    if not evaluator.adapter_available("gemma2"):
        print(f"[skipped] {path.name} — gemma2 adapter not trained yet")
        return None
    if not classifier_available():
        print(f"[skipped] {path.name} — classifier weights missing "
              f"({CLASSIFIER_DIR})")
        return None

    cases = load_cases()
    tasks = flat_turns(cases)
    print(f"[running] {path.name} ({len(cases)} cases, {len(tasks)} client turns)")
    start = time.time()

    diags = diagnose_all([t["message"] for _, t in tasks])

    if system == "pipeline_single":
        sys_text = single_system_text()
        gen_idx = list(range(len(tasks)))
        prompts = [gemma_chat_prompt(sys_text, t["history"], t["message"])
                   for _, t in tasks]
        summaries = [None] * len(tasks)
        recents = [t["history"] for _, t in tasks]
    else:
        # The app's memory windowing (nodes.load_context): the last
        # RECENT_TURNS exchanges verbatim, the rest through the summary.
        fulls = [t["history"] for _, t in tasks]
        recents = [h[-RECENT_TURNS:] if RECENT_TURNS > 0 else [] for h in fulls]
        olders = [h[:-RECENT_TURNS] if RECENT_TURNS > 0 else list(h)
                  for h in fulls]
        summaries = summarize_all(olders, fulls)
        gen_idx = [i for i, d in enumerate(diags) if not d["escalated"]]
        prompts = [gemma_chat_prompt(composed_system_text(summaries[i]),
                                     recents[i], tasks[i][1]["message"])
                   for i in gen_idx]
        skipped = len(tasks) - len(gen_idx)
        if skipped:
            print(f"          {skipped} escalated turn(s) get the fixed "
                  f"crisis message")

    model, tokenizer = evaluator.load_system("gemma2", "tuned")
    tokenizer.truncation_side = "left"        # long histories drop OLD turns
    gen_preds = evaluator.generate_predictions(
        model, tokenizer, prompts, "gemma2",
        prompt_fn=lambda p: p, max_length=GEN_MAX_LENGTH)
    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()

    predictions = [CRISIS_MESSAGE] * len(tasks)
    for idx, pred in zip(gen_idx, gen_preds):
        predictions[idx] = pred

    evaluator.GEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for (case_id, t), pred, diag, summary, recent in zip(
                tasks, predictions, diags, summaries, recents):
            f.write(json.dumps({
                "case": case_id, "turn": t["turn"],
                "history": t["history"], "message": t["message"],
                "reference": t["reference"], "prediction": pred,
                "summary": summary, "verbatimTurns": len(recent), **diag,
            }, ensure_ascii=False) + "\n")
    print(f"          done in {(time.time() - start) / 60:.1f} min -> {path.name}")
    return path


# ---------------------------------------------------------------------------
# CEHS judging (SoulChat Table 2, arXiv:2311.00273) via the shared GLM judge
# ---------------------------------------------------------------------------
CEHS_DIMENSIONS = {"content": 2, "empathy": 2, "helpfulness": 2, "safety": 1}
_CEHS_TEMPLATE = (HERE / "cehs_prompt.txt").read_text(encoding="utf-8")


def build_cehs_prompt(history, message, reply):
    conversation = format_history(history) if history else "(first message)"
    return (_CEHS_TEMPLATE
            .replace("<<CONVERSATION>>", conversation)
            .replace("<<MESSAGE>>", message.strip())
            .replace("<<REPLY>>", reply.strip()))


def parse_cehs_output(text):
    """Validate the judge's JSON against the CEHS ranges (0-2/0-2/0-2/0-1)."""
    import re
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    data = None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    if not isinstance(data, dict) or not isinstance(data.get("scores"), dict):
        raise ValueError(f"no CEHS scores in judge output: {str(text)[:120]!r}")
    scores = {}
    for dim, hi in CEHS_DIMENSIONS.items():
        value = data["scores"].get(dim)
        if not isinstance(value, (int, float)) or isinstance(value, bool) \
                or not 0 <= value <= hi:
            raise ValueError(f"bad CEHS score for {dim}: {value!r}")
        scores[dim] = float(value)
    scores["total"] = round(sum(scores.values()), 2)
    return {"scores": scores, "justification": str(data.get("justification", ""))}


def judge_cehs(client, records_by_system, out_path, delay=1.1, max_retries=5):
    """Judge every (system, case, turn) reply once. Appends jsonl lines with
    custom_id '<system>__<case>_<turn>' and skips ids already present, so
    interrupting and re-running is always safe (same contract as
    llm_judge.judge_many)."""
    import openai

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["custom_id"])
                except (json.JSONDecodeError, KeyError):
                    pass

    todo = [(f"{system}__{r['case']}_{r['turn']}", r)
            for system, recs in records_by_system.items() for r in recs]
    todo = [t for t in todo if t[0] not in done]
    print(f"{len(todo)} replies to judge ({len(done)} already in {out_path.name})")

    with open(out_path, "a", encoding="utf-8") as f:
        for n, (custom_id, r) in enumerate(todo, 1):
            prompt = build_cehs_prompt(r["history"], r["message"], r["prediction"])
            record = {"custom_id": custom_id, "ok": False, "error": "not attempted"}
            for attempt in range(max_retries):
                try:
                    resp = llm_judge._chat(client, llm_judge.JUDGE_MODEL, prompt)
                    text = resp.choices[0].message.content or ""
                    record = {"custom_id": custom_id, "ok": True,
                              **parse_cehs_output(text)}
                    break
                except openai.RateLimitError:
                    record["error"] = "rate_limited"
                    time.sleep(min(60, 5 * 2 ** attempt))
                except (openai.APIStatusError, openai.APIConnectionError) as e:
                    record["error"] = type(e).__name__
                    time.sleep(min(60, 2 * 2 ** attempt))
                except (ValueError, AttributeError, IndexError) as e:
                    record["error"] = f"parse: {str(e)[:80]}"
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            if not record["ok"]:
                print(f"  ! {custom_id}: {record['error']}")
            if n % 10 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)} judged", end="\r")
            time.sleep(delay)
    print()
