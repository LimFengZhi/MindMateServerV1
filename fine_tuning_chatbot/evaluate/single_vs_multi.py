"""Single-agent vs multi-agent pipeline evaluation on MULTI-TURN counseling
conversations (Jingy2000/multi-turn-counsel-chat — CounselChat Q&A expanded to
client/counselor dialogues with GPT-4).

n_cases conversations (stratified by category) are replayed FREE-RUNNING:
the client side is scripted from the dataset, but each arm's conversation
history is its OWN previous replies — the dataset's counselor replies are
ignored (stored only as unused 'reference'), so the evaluation measures each
architecture living with its own output, like deployment. The SAME tuned
model (single_vs_multi.model_key in config.yaml) answers in both arms — only
the app's architecture differs:

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
CASE_CATEGORIES = SVM_CFG.get(
    "case_categories", ["Suicidal", "Depression", "Stress", "Anxiety", "Bipolar"])
MODEL_KEY = SVM_CFG.get("model_key", "gemma2")  # which tuned model both arms use
LABELS_CACHE = ft_utils.PROCESSED_DIR / "counselchat_case_labels.json"

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


def chat_prompt(system_text, history, message):
    """MODEL_KEY's chat template over (system, history, message), matching the
    app's LocalChatModel formatting for that family — Gemma folds the system
    text into the first user turn (no system role); Qwen3 gets a real system
    turn carrying the /no_think control the fine-tune was trained with."""
    if MODEL_KEY == "gemma2":
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

    if MODEL_KEY == "qwen3":
        parts = [f"<|im_start|>system\n/no_think\n{system_text}<|im_end|>\n"]
        for client_msg, counselor_msg in history:
            parts.append(f"<|im_start|>user\n{client_msg}<|im_end|>\n")
            parts.append(f"<|im_start|>assistant\n{counselor_msg}<|im_end|>\n")
        parts.append(f"<|im_start|>user\n{message}<|im_end|>\n")
        parts.append("<|im_start|>assistant\n")
        return "".join(parts)

    if MODEL_KEY == "llama32":
        parts = ["<|begin_of_text|><|start_header_id|>system<|end_header_id|>"
                 f"\n\n{system_text}<|eot_id|>"]
        for client_msg, counselor_msg in history:
            parts.append(f"<|start_header_id|>user<|end_header_id|>\n\n{client_msg}<|eot_id|>")
            parts.append(f"<|start_header_id|>assistant<|end_header_id|>\n\n{counselor_msg}<|eot_id|>")
        parts.append(f"<|start_header_id|>user<|end_header_id|>\n\n{message}<|eot_id|>")
        parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
        return "".join(parts)

    raise ValueError(f"unknown model_key '{MODEL_KEY}'")


def format_history(history):
    """[(client, counselor)] -> the transcript text the summarizer reads
    (same shape as app/agents/prompts.py format_history)."""
    lines = []
    for client_msg, counselor_msg in history:
        lines.append(f"User: {client_msg}")
        lines.append(f"Companion: {counselor_msg}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cases: stratified by category, replayed teacher-forced
# ---------------------------------------------------------------------------
def _client_text(conv):
    return " ".join(m["content"] for m in conv["messages"]
                    if m["role"] == "client")


def case_labels(data):
    """One category per conversation, assigned with the APP's own logic:
    crisis keywords in any client turn -> 'Suicidal'; otherwise the RoBERTa
    classifier's label over the client's concatenated messages. Cached to
    processed/ so the 863 classifications run once."""
    if LABELS_CACHE.exists():
        cached = json.loads(LABELS_CACHE.read_text(encoding="utf-8"))
        if len(cached) == len(data):
            return cached

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(CLASSIFIER_DIR))
    model = AutoModelForSequenceClassification.from_pretrained(str(CLASSIFIER_DIR))
    model.eval()

    labels = []
    texts = [_client_text(d) for d in data]
    for i in range(0, len(texts), 32):
        enc = tok(texts[i:i + 32], return_tensors="pt", padding=True,
                  truncation=True, max_length=512)
        with torch.inference_mode():
            idx = model(**enc).logits.argmax(dim=-1)
        labels.extend(model.config.id2label[int(k)] for k in idx)
    del model, tok
    gc.collect()

    labels = ["Suicidal" if guards.crisis_keywords_present(t) else l
              for t, l in zip(texts, labels)]
    LABELS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    LABELS_CACHE.write_text(json.dumps(labels), encoding="utf-8")
    return labels


def _select_cases(data):
    """Seeded stratified pick: n_cases spread evenly over case_categories,
    topped up at random if a category has too few conversations."""
    labels = case_labels(data)
    rng = random.Random(ft_utils.SEED)
    per_cat = max(1, N_CASES // len(CASE_CATEGORIES))
    picked = []
    for cat in CASE_CATEGORIES:
        pool = [i for i, l in enumerate(labels) if l == cat and i not in picked]
        picked += rng.sample(pool, min(per_cat, len(pool)))
    if len(picked) < N_CASES:
        rest = [i for i in range(len(data)) if i not in picked]
        picked += rng.sample(rest, N_CASES - len(picked))
    return sorted(picked[:N_CASES]), labels


def load_cases():
    """The stratified cases -> replay tasks. The dataset's leading counselor
    greeting is dropped (the app has no bot-first turn; the frontend welcome
    bubble is never part of the pipeline), leaving clean (client, counselor)
    exchange pairs.

    Returns a list of cases: {"case": i, "category": label, "turns":
    [{"turn", "history" [(client, counselor), ...], "message", "reference"},
    ...]}."""
    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"{RAW_PATH} missing — download it once with:\n"
            f"  curl -L https://huggingface.co/datasets/{HF_ID}/resolve/main/"
            f"all_dialogue_cleaned.json -o \"{RAW_PATH}\"")
    data = json.loads(RAW_PATH.read_text(encoding="utf-8"))

    picked, labels = _select_cases(data)

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
        cases.append({"case": case_id, "category": labels[case_id],
                      "turns": turns})
    return cases


def flat_turns(cases):
    return [(c, t) for c in cases for t in c["turns"]]


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


def _load_summarizer():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(SUMMARIZER_ID)
    model = AutoModelForCausalLM.from_pretrained(
        SUMMARIZER_ID, dtype=torch.bfloat16, device_map="auto")
    model.eval()
    return tok, model


def summarize_batch(tok, model, olders, fulls):
    """The APP's summarizer (summarise_prompt.txt, which also records what the
    companion last asked/suggested) over each item's OLDER history — the part
    outside the verbatim window. Wordings mirror nodes.summarize: no history
    at all -> first-turn text; history but nothing old enough -> just-begun."""
    import torch

    summaries = [FIRST_TURN_SUMMARY if not full else JUST_BEGUN_SUMMARY
                 for full in fulls]
    system_text = _prompt_text("summarise_prompt.txt")
    for i, older in enumerate(olders):
        if not older:
            continue
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user",
             "content": f"CONVERSATION:\n{format_history(older)}"},
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
    return summaries


# ---------------------------------------------------------------------------
# Generation (cached like evaluator's passes)
# ---------------------------------------------------------------------------
SYSTEMS = ("pipeline_single", "pipeline_multi")
GEN_MAX_LENGTH = 4096       # multi-turn single-agent prompts exceed the 1024
                            # training window; these models handle it easily


def generation_path(system):
    return evaluator.GEN_DIR / f"{system}.jsonl"


def load_generations(system):
    path = generation_path(system)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def generate_and_store(system, force=False):
    """One FREE-RUNNING replay pass for 'pipeline_single' or 'pipeline_multi'
    -> cached jsonl (one line per case x client turn).

    Free-running: the CLIENT side is scripted from the dataset, but each
    arm's conversation history is its OWN previous replies — the dataset's
    counselor replies are never used as context (stored only as unused
    'reference'). Turns therefore run depth-by-depth: every case's turn t
    needs that case's reply t-1. The stored 'history' is the arm's own
    conversation so far, which is also what the CEHS judge reads."""
    import torch

    assert system in SYSTEMS, f"unknown system '{system}'"
    path = generation_path(system)
    if path.exists() and not force:
        print(f"[cached]  {path.name}")
        return path
    if not evaluator.adapter_available(MODEL_KEY):
        print(f"[skipped] {path.name} — {MODEL_KEY} adapter not trained yet")
        return None
    if not classifier_available():
        print(f"[skipped] {path.name} — classifier weights missing "
              f"({CLASSIFIER_DIR})")
        return None

    cases = load_cases()
    n_turns = sum(len(c["turns"]) for c in cases)
    print(f"[running] {path.name} ({len(cases)} cases, {n_turns} client turns, "
          f"free-running)")
    start = time.time()

    # Diagnosis depends only on the scripted client message — same either way.
    all_tasks = flat_turns(cases)
    diags = diagnose_all([t["message"] for _, t in all_tasks])
    diag_map = {(c["case"], t["turn"]): d
                for (c, t), d in zip(all_tasks, diags)}

    model, tokenizer = evaluator.load_system(MODEL_KEY, "tuned")
    tokenizer.truncation_side = "left"        # long histories drop OLD turns
    sum_tok = sum_model = None
    if system == "pipeline_multi":
        sum_tok, sum_model = _load_summarizer()
    sys_text_single = single_system_text()

    own_hist = {c["case"]: [] for c in cases}
    records = []
    max_depth = max(len(c["turns"]) for c in cases)
    for depth in range(max_depth):
        active = [(c, c["turns"][depth]) for c in cases
                  if len(c["turns"]) > depth]
        fulls = [own_hist[c["case"]] for c, _ in active]

        if system == "pipeline_multi":
            # The app's memory windowing (nodes.load_context) over OWN history.
            recents = [h[-RECENT_TURNS:] if RECENT_TURNS > 0 else []
                       for h in fulls]
            olders = [h[:-RECENT_TURNS] if RECENT_TURNS > 0 else list(h)
                      for h in fulls]
            summaries = summarize_batch(sum_tok, sum_model, olders, fulls)
        else:
            recents = fulls                    # single sees everything verbatim
            summaries = [None] * len(active)

        prompts, gen_slots = [], []
        for i, (c, t) in enumerate(active):
            d = diag_map[(c["case"], t["turn"])]
            if system == "pipeline_multi" and d["escalated"]:
                continue                       # crisis routing: fixed message
            stext = (sys_text_single if system == "pipeline_single"
                     else composed_system_text(summaries[i]))
            prompts.append(chat_prompt(stext, recents[i], t["message"]))
            gen_slots.append(i)

        preds = evaluator.generate_predictions(
            model, tokenizer, prompts, MODEL_KEY,
            prompt_fn=lambda p: p, max_length=GEN_MAX_LENGTH) if prompts else []
        replies = [CRISIS_MESSAGE] * len(active)
        for slot, pred in zip(gen_slots, preds):
            replies[slot] = pred

        for i, (c, t) in enumerate(active):
            records.append({
                "case": c["case"], "category": c["category"], "turn": t["turn"],
                "history": list(own_hist[c["case"]]), "message": t["message"],
                "reference": t["reference"], "prediction": replies[i],
                "summary": summaries[i], "verbatimTurns": len(recents[i]),
                **diag_map[(c["case"], t["turn"])],
            })
            own_hist[c["case"]].append((t["message"], replies[i]))
        print(f"    depth {depth + 1}/{max_depth} done")

    del model, tokenizer
    if sum_model is not None:
        del sum_model, sum_tok
    gc.collect()
    torch.cuda.empty_cache()

    records.sort(key=lambda r: (r["case"], r["turn"]))
    evaluator.GEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
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


def judge_cehs(client, records_by_system, out_path, delay=1.1, max_retries=5,
               model=None):
    """Judge every (system, case, turn) reply once. Appends jsonl lines with
    custom_id '<system>__<case>_<turn>' and skips ids already present, so
    interrupting and re-running is always safe (same contract as
    llm_judge.judge_many). model overrides the primary judge (second-judge
    runs pass their own model + a slower delay)."""
    import openai

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()  # only SUCCESSFUL verdicts — failures are retried on re-run
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("ok"):
                        done.add(rec["custom_id"])
                except (json.JSONDecodeError, KeyError):
                    pass

    todo = [(f"{system}__{r['case']}_{r['turn']}", r)
            for system, recs in records_by_system.items() for r in recs]
    todo = [t for t in todo if t[0] not in done]
    print(f"{len(todo)} replies to judge ({len(done)} already in {out_path.name})")

    # A killed run can leave a final line without its newline — appending
    # would glue records. Make sure the file ends cleanly first.
    if out_path.exists() and out_path.stat().st_size:
        with open(out_path, "rb+") as _f:
            _f.seek(-1, 2)
            if _f.read(1) != b"\n":
                _f.write(b"\n")

    with open(out_path, "a", encoding="utf-8") as f:
        for n, (custom_id, r) in enumerate(todo, 1):
            prompt = build_cehs_prompt(r["history"], r["message"], r["prediction"])
            record = {"custom_id": custom_id, "ok": False, "error": "not attempted"}
            for attempt in range(max_retries):
                try:
                    resp = llm_judge._chat(client, model or llm_judge.JUDGE_MODEL, prompt)
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
