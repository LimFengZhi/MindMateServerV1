"""
llm_judge.py — reusable LLM-as-judge for counseling responses.

Scores a (patient question, assistant response) pair on the 7 counseling
dimensions from the MentalChat16K paper (Xu et al., arXiv:2503.13509),
absolute 1-10 each. The judge is GLM-4.7-Flash (free on Z.ai) called through
Z.ai's OpenAI-compatible endpoint; model/base_url/key env var come from
config.yaml's `judge:` block. The rubric text lives in judge_prompt.txt.

Used by evaluate_llm_judge.ipynb (judging the stored test-set generations
from evaluate_metric.ipynb) and designed for reuse by the later single-agent vs multi-agent
evaluation — it only ever sees (question, response) pairs, wherever the
responses came from.

Flow:
    client = make_client()                       # key from .env (GLM_API_KEY)
    verdict = judge_one(client, q, r)            # smoke test / small runs
    items = [(custom_id, question, response), ...]
    judge_many(client, items, out_path)          # sequential (free tier ~1 req/s),
                                                 # appends jsonl incrementally,
                                                 # skips ids already in out_path
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # ft root (ft_utils, config)
import ft_utils

ROOT = Path(__file__).resolve().parent

DIMENSIONS = [
    "active_listening",
    "empathy_validation",
    "safety_trustworthiness",
    "openmindedness_nonjudgment",
    "clarity_encouragement",
    "boundaries_ethical",
    "holistic_approach",
]

JUDGE_CFG = ft_utils.CFG["judge"]
JUDGE_MODEL = JUDGE_CFG["model"]
JUDGE_BASE_URL = JUDGE_CFG["base_url"]
JUDGE_KEY_ENV = JUDGE_CFG.get("api_key_env", "GLM_API_KEY")
JUDGE_MAX_TOKENS = JUDGE_CFG.get("max_tokens", 1024)

_PROMPT_TEMPLATE = (ROOT / "judge_prompt.txt").read_text(encoding="utf-8")


def build_judge_prompt(question, response):
    return (_PROMPT_TEMPLATE
            .replace("<<QUESTION>>", question.strip())
            .replace("<<RESPONSE>>", response.strip()))


def make_client():
    """OpenAI-compatible client pointed at Z.ai. Key comes from the .env var
    named in config (GLM_API_KEY) — free key at https://z.ai"""
    from openai import OpenAI

    key = os.getenv(JUDGE_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{JUDGE_KEY_ENV} is empty — get a free key at https://z.ai and "
            "paste it into the project .env file")
    return OpenAI(api_key=key, base_url=JUDGE_BASE_URL)


# ---------------------------------------------------------------------------
# Judge calls
# ---------------------------------------------------------------------------

_THINKING_SUPPORTED = True  # GLM thinking switch; auto-disabled if rejected


def _chat(client, model, prompt):
    """One chat.completions call; asks GLM to skip its thinking phase (faster,
    free-tier friendly). Falls back automatically if the endpoint rejects the
    non-standard `thinking` field."""
    global _THINKING_SUPPORTED
    kwargs = dict(
        model=model,
        max_tokens=JUDGE_MAX_TOKENS,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    if _THINKING_SUPPORTED:
        try:
            return client.chat.completions.create(
                extra_body={"thinking": {"type": "disabled"}}, **kwargs)
        except Exception as e:
            import openai
            if isinstance(e, openai.BadRequestError):
                _THINKING_SUPPORTED = False  # retry below without the field
            else:
                raise
    return client.chat.completions.create(**kwargs)


def judge_one(client, question, response, model=None):
    """One live judge call. Returns {"scores": {...}, "justification": str}."""
    resp = _chat(client, model or JUDGE_MODEL, build_judge_prompt(question, response))
    if not getattr(resp, "choices", None):
        raise ValueError(f"judge API returned no choices — raw response: {str(resp)[:200]}")
    text = resp.choices[0].message.content or ""
    return parse_judge_output(text)


def judge_many(client, items, out_path, delay=1.1, max_retries=5, model=None):
    """Judge (custom_id, question, response) items sequentially — the Z.ai
    free tier allows ~1 request/second, hence the delay.

    Appends one jsonl line per item to out_path AS IT GOES and skips ids
    already present, so interrupting and re-running is always safe."""
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

    todo = [item for item in items if item[0] not in done]
    print(f"{len(todo)} to judge ({len(done)} already in {out_path.name})")

    with open(out_path, "a", encoding="utf-8") as f:
        for n, (custom_id, question, response) in enumerate(todo, 1):
            record = {"custom_id": custom_id, "ok": False, "error": "not attempted"}
            for attempt in range(max_retries):
                try:
                    verdict = judge_one(client, question, response, model=model)
                    record = {"custom_id": custom_id, "ok": True, **verdict}
                    break
                except openai.RateLimitError:
                    record["error"] = "rate_limited"
                    time.sleep(min(60, 5 * 2 ** attempt))
                except (openai.APIStatusError, openai.APIConnectionError) as e:
                    record["error"] = type(e).__name__
                    time.sleep(min(60, 2 * 2 ** attempt))
                except ValueError as e:  # unparseable verdict — retry
                    record["error"] = f"parse: {str(e)[:80]}"
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            if not record["ok"]:
                print(f"  ! {custom_id}: {record['error']}")
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)} judged", end="\r")
            time.sleep(delay)
    print()


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

def parse_judge_output(text):
    """Extract and validate the judge's JSON verdict.
    Returns {"scores": {dim: float}, "justification": str}. Raises ValueError
    on malformed output (callers count failures rather than crash)."""
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
    if not isinstance(data, dict):
        raise ValueError(f"no JSON object in judge output: {text[:120]!r}")

    raw_scores = data.get("scores")
    if not isinstance(raw_scores, dict):
        raise ValueError("judge output has no 'scores' object")

    scores = {}
    for dim in DIMENSIONS:
        value = raw_scores.get(dim)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 1 <= value <= 10:
            raise ValueError(f"bad score for {dim}: {value!r}")
        scores[dim] = float(value)
    return {"scores": scores, "justification": str(data.get("justification", ""))}
