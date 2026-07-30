# LLM-as-Judge Report — Psych8k benchmark (200 questions)

Judge: `glm-4.7-flash` via Z.ai (OpenAI-compatible API); rubric: the MentalChat16K paper's 7 counseling dimensions, absolute 1-10 each (see `judge_prompt.txt`).

## Mean scores per system

| model   | dataset       |   active_listening |   empathy_validation |   safety_trustworthiness |   openmindedness_nonjudgment |   clarity_encouragement |   boundaries_ethical |   holistic_approach |   overall |
|:--------|:--------------|-------------------:|---------------------:|-------------------------:|-----------------------------:|------------------------:|---------------------:|--------------------:|----------:|
| gemma2  | amod          |               1.01 |                 1.03 |                     1.24 |                         1.2  |                    1    |                 1.25 |                1.01 |      1.11 |
| gemma2  | mentalchat16k |               1.12 |                 1.14 |                     1.67 |                         1.65 |                    1.08 |                 1.65 |                1.09 |      1.34 |
| llama32 | amod          |               1    |                 1    |                     1    |                         1    |                    1    |                 1    |                1    |      1    |
| llama32 | mentalchat16k |               1    |                 1.01 |                     1.1  |                         1.1  |                    1    |                 1.09 |                1    |      1.04 |
| qwen3   | amod          |               1.16 |                 1.25 |                     2.5  |                         2.63 |                    1.12 |                 2.52 |                1.06 |      1.75 |
| qwen3   | mentalchat16k |               2.43 |                 2.46 |                     5.28 |                         5.32 |                    2.6  |                 5.34 |                2.76 |      3.74 |

## Winner per dimension

- **active_listening**: qwen3 tuned on mentalchat16k (2.43)
- **empathy_validation**: qwen3 tuned on mentalchat16k (2.46)
- **safety_trustworthiness**: qwen3 tuned on mentalchat16k (5.29)
- **openmindedness_nonjudgment**: qwen3 tuned on mentalchat16k (5.33)
- **clarity_encouragement**: qwen3 tuned on mentalchat16k (2.60)
- **boundaries_ethical**: qwen3 tuned on mentalchat16k (5.34)
- **holistic_approach**: qwen3 tuned on mentalchat16k (2.75)
- **overall**: qwen3 tuned on mentalchat16k (3.74)

## Overall ranking

| model   | dataset       |   overall |
|:--------|:--------------|----------:|
| qwen3   | mentalchat16k |      3.74 |
| qwen3   | amod          |      1.75 |
| gemma2  | mentalchat16k |      1.34 |
| gemma2  | amod          |      1.11 |
| llama32 | mentalchat16k |      1.04 |
| llama32 | amod          |      1    |

> Notes: single LLM judge, no human calibration — scores are comparable within this run, not across judges or prompts. The benchmark is disjoint from both training datasets (verified in eda_psych8k.ipynb).
