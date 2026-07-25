# Evaluation Report — Counselor Fine-Tuning Study (3 models × 2 datasets)

Each tuned adapter is scored on **its own dataset's held-out test split** (amod multi-reference), next to the un-tuned base model on the same split.

## Scores

| model   | dataset       | variant   |    n |   bertscore_f1 |   bleu |   rouge_l |   flesch_reading_ease |   flesch_kincaid_grade |
|:--------|:--------------|:----------|-----:|---------------:|-------:|----------:|----------------------:|-----------------------:|
| gemma2  | amod          | tuned     |   71 |         0.802  | 0.0109 |    0.1071 |                 75.78 |                   6.85 |
| gemma2  | amod          | base      |   71 |         0.7977 | 0.0179 |    0.1278 |                 77.85 |                   4.85 |
| llama32 | amod          | tuned     |   71 |         0.7884 | 0.0077 |    0.0752 |                 30.83 |                  16.23 |
| llama32 | amod          | base      |   71 |         0.7896 | 0.0107 |    0.0965 |                 53.98 |                   8.47 |
| qwen3   | amod          | tuned     |   71 |         0.7349 | 0.0036 |    0.0929 |                 68.83 |                   8.81 |
| qwen3   | amod          | base      |   71 |         0.8475 | 0.039  |    0.165  |                 68.34 |                   7.67 |
| gemma2  | mentalchat16k | tuned     | 1591 |         0.8299 | 0.0231 |    0.1322 |                 63.15 |                   8.39 |
| gemma2  | mentalchat16k | base      | 1591 |         0.8228 | 0.024  |    0.1392 |                 61.32 |                   8.29 |
| llama32 | mentalchat16k | tuned     | 1591 |         0.8192 | 0.0231 |    0.132  |                 37.47 |                  13.25 |
| llama32 | mentalchat16k | base      | 1591 |         0.8052 | 0.0129 |    0.1144 |                 59.33 |                   8.86 |
| qwen3   | mentalchat16k | tuned     | 1591 |         0.859  | 0.0539 |    0.1985 |                 35.59 |                  13.38 |
| qwen3   | mentalchat16k | base      | 1591 |         0.8605 | 0.0284 |    0.1742 |                 63.42 |                   8.21 |

## Winners — amod test set

- **bertscore_f1**: gemma2 (0.802)
- **bleu**: gemma2 (0.0109)
- **rouge_l**: gemma2 (0.1071)

## Winners — mentalchat16k test set

- **bertscore_f1**: qwen3 (0.859)
- **bleu**: qwen3 (0.0539)
- **rouge_l**: qwen3 (0.1985)

## Fine-tuning lift (tuned − base, BERTScore F1, same test set)

| model   | dataset       |   bertscore_f1_base |   bertscore_f1_tuned |   delta_bertscore |
|:--------|:--------------|--------------------:|---------------------:|------------------:|
| gemma2  | amod          |              0.7977 |               0.802  |            0.0043 |
| llama32 | amod          |              0.7896 |               0.7884 |           -0.0012 |
| qwen3   | amod          |              0.8475 |               0.7349 |           -0.1126 |
| gemma2  | mentalchat16k |              0.8228 |               0.8299 |            0.0071 |
| llama32 | mentalchat16k |              0.8052 |               0.8192 |            0.014  |
| qwen3   | mentalchat16k |              0.8605 |               0.859  |           -0.0015 |

## Training manifests

- `gemma2` on `amod`: 53.6 min, final train loss 1.4449679632172505, best eval loss 1.8106328248977661
- `llama32` on `amod`: 27.3 min, final train loss 1.7776488222148084, best eval loss 1.9952093362808228
- `qwen3` on `amod`: 42.7 min, final train loss 1.839948478687223, best eval loss 1.9845921993255615
- `gemma2` on `mentalchat16k`: 454.3 min, final train loss 0.726450298936499, best eval loss 0.7712023258209229
- `llama32` on `mentalchat16k`: 203.6 min, final train loss 0.8522480456895346, best eval loss 0.8599464893341064
- `qwen3` on `mentalchat16k`: 317.5 min, final train loss 0.8463166000781305, best eval loss 0.8406127095222473

> ⚠ Raw reference-based scores from the two test sets are not directly comparable (reference style and length differ between datasets). Use the per-dataset rankings and the tuned-vs-base Δ for cross-dataset conclusions.
