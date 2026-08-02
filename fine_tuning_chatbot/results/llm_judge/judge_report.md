# LLM-as-Judge Report (7 counseling dimensions, GLM-4.7-Flash)

Judged 200 seeded-sample questions from the SAME MentalChat16K test-set generations used by the metric evaluation (`results/generations/`).

## Mean scores

|                      |   active_listening |   empathy_validation |   safety_trustworthiness |   openmindedness_nonjudgment |   clarity_encouragement |   boundaries_ethical |   holistic_approach |   overall |
|:---------------------|-------------------:|---------------------:|-------------------------:|-----------------------------:|------------------------:|---------------------:|--------------------:|----------:|
| ('gemma2', 'base')   |               7.55 |                 7.42 |                     8.39 |                         9.22 |                    8.2  |                 7.66 |                6.36 |      7.83 |
| ('gemma2', 'tuned')  |               7.79 |                 7.04 |                     8.6  |                         9.1  |                    8.07 |                 7.77 |                6.8  |      7.88 |
| ('llama32', 'base')  |               6.64 |                 6.1  |                     8.14 |                         8.86 |                    7.7  |                 7.7  |                5.88 |      7.29 |
| ('llama32', 'tuned') |               7.8  |                 7.07 |                     8.62 |                         9.16 |                    7.99 |                 7.89 |                6.84 |      7.91 |
| ('qwen3', 'base')    |               8.11 |                 8.24 |                     8.64 |                         9.49 |                    8.26 |                 7.92 |                6.9  |      8.22 |
| ('qwen3', 'tuned')   |               7.74 |                 7.01 |                     8.63 |                         9.09 |                    8.03 |                 7.87 |                6.86 |      7.89 |

**Best overall:** qwen3 (base) at 8.22/10
