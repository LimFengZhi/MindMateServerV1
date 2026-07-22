# LLM-as-Judge Report — Psych8k benchmark (200 questions)

Judge: `glm-4.7-flash` via Z.ai (OpenAI-compatible API); rubric: the MentalChat16K paper's 7 counseling dimensions, absolute 1-10 each (see `judge_prompt.txt`).

## Mean scores per system

| model   | dataset       |   active_listening |   empathy_validation |   safety_trustworthiness |   openmindedness_nonjudgment |   clarity_encouragement |   boundaries_ethical |   holistic_approach |   overall |
|:--------|:--------------|-------------------:|---------------------:|-------------------------:|-----------------------------:|------------------------:|---------------------:|--------------------:|----------:|
| gemma2  | amod          |               2.45 |                 2.78 |                     5.44 |                         5.75 |                    2.8  |                 5.55 |                2.37 |      3.88 |
| gemma2  | mentalchat16k |               7.34 |                 6.72 |                     8.9  |                         8.81 |                    7.42 |                 8.59 |                6.66 |      7.78 |
| llama32 | amod          |               1.73 |                 1.98 |                     4.66 |                         5.07 |                    1.88 |                 4.95 |                1.76 |      3.15 |
| llama32 | mentalchat16k |               6.84 |                 6.5  |                     8.59 |                         8.76 |                    6.96 |                 8.32 |                6.74 |      7.53 |
| qwen3   | amod          |               2.64 |                 2.94 |                     5.64 |                         6.38 |                    3.64 |                 5.95 |                2.84 |      4.29 |
| qwen3   | mentalchat16k |               6.98 |                 6.63 |                     8.72 |                         8.72 |                    7.09 |                 8.28 |                6.85 |      7.61 |

## Winner per dimension

- **active_listening**: gemma2 tuned on mentalchat16k (7.33)
- **empathy_validation**: gemma2 tuned on mentalchat16k (6.72)
- **safety_trustworthiness**: gemma2 tuned on mentalchat16k (8.89)
- **openmindedness_nonjudgment**: gemma2 tuned on mentalchat16k (8.81)
- **clarity_encouragement**: gemma2 tuned on mentalchat16k (7.42)
- **boundaries_ethical**: gemma2 tuned on mentalchat16k (8.59)
- **holistic_approach**: qwen3 tuned on mentalchat16k (6.85)
- **overall**: gemma2 tuned on mentalchat16k (7.78)

## Overall ranking

| model   | dataset       |   overall |
|:--------|:--------------|----------:|
| gemma2  | mentalchat16k |      7.78 |
| qwen3   | mentalchat16k |      7.61 |
| llama32 | mentalchat16k |      7.53 |
| qwen3   | amod          |      4.29 |
| gemma2  | amod          |      3.88 |
| llama32 | amod          |      3.15 |

> Notes: single LLM judge, no human calibration — scores are comparable within this run, not across judges or prompts. The benchmark is disjoint from both training datasets (verified in eda_psych8k.ipynb).
