# Evaluation Report — Counselor Fine-Tuning Study (3 models × 2 datasets)

Each tuned adapter is scored on **its own dataset's held-out test split** (amod multi-reference), next to the un-tuned base model on the same split.

## Scores

| model   | dataset       | variant   |    n |   bertscore_f1 |   bleu |   rouge_l |   flesch_reading_ease |   flesch_kincaid_grade |
|:--------|:--------------|:----------|-----:|---------------:|-------:|----------:|----------------------:|-----------------------:|
| gemma2  | amod          | tuned     |   71 |         0.8338 | 0.0351 |    0.1652 |                 75.97 |                   6.47 |
| gemma2  | amod          | base      |   71 |         0.797  | 0.0176 |    0.1281 |                 81.88 |                   4.61 |
| llama32 | amod          | tuned     |   71 |         0.8207 | 0.0337 |    0.1523 |                 74.19 |                   6.59 |
| llama32 | amod          | base      |   71 |         0.791  | 0.0117 |    0.0974 |                 70.13 |                   6.21 |
| qwen3   | amod          | tuned     |   71 |         0.8292 | 0.0425 |    0.17   |                 75.45 |                   6.04 |
| qwen3   | amod          | base      |   71 |         0.8475 | 0.039  |    0.165  |                 68.34 |                   7.67 |
| gemma2  | mentalchat16k | tuned     | 1591 |         0.8817 | 0.0765 |    0.2308 |                 45.51 |                  11.25 |
| gemma2  | mentalchat16k | base      | 1591 |         0.8091 | 0.0153 |    0.126  |                 74.28 |                   6.05 |
| llama32 | mentalchat16k | tuned     | 1591 |         0.881  | 0.0852 |    0.2306 |                 45.64 |                  11.27 |
| llama32 | mentalchat16k | base      | 1591 |         0.795  | 0.0119 |    0.1125 |                 46.13 |                  10.57 |
| qwen3   | mentalchat16k | tuned     | 1591 |         0.8814 | 0.0862 |    0.2309 |                 45.3  |                  11.37 |
| qwen3   | mentalchat16k | base      | 1591 |         0.8604 | 0.0285 |    0.1742 |                 63.46 |                   8.2  |

## Winners — amod test set

- **bertscore_f1**: gemma2 (0.8338)
- **bleu**: qwen3 (0.0425)
- **rouge_l**: qwen3 (0.17)

## Winners — mentalchat16k test set

- **bertscore_f1**: gemma2 (0.8817)
- **bleu**: qwen3 (0.0862)
- **rouge_l**: qwen3 (0.2309)

## Fine-tuning lift (tuned − base, BERTScore F1, same test set)

| model   | dataset       |   bertscore_f1_base |   bertscore_f1_tuned |   delta_bertscore |
|:--------|:--------------|--------------------:|---------------------:|------------------:|
| gemma2  | amod          |              0.797  |               0.8338 |            0.0368 |
| llama32 | amod          |              0.791  |               0.8207 |            0.0297 |
| qwen3   | amod          |              0.8475 |               0.8292 |           -0.0183 |
| gemma2  | mentalchat16k |              0.8091 |               0.8817 |            0.0726 |
| llama32 | mentalchat16k |              0.795  |               0.881  |            0.086  |
| qwen3   | mentalchat16k |              0.8604 |               0.8814 |            0.021  |

## Training manifests

- `gemma2` on `amod`: 50.1 min, final train loss 1.5712744711391167, best eval loss 1.7959891557693481
- `llama32` on `amod`: 24.6 min, final train loss 1.9664805600725868, best eval loss 2.076077461242676
- `qwen3` on `amod`: 39.8 min, final train loss 1.9650022872073258, best eval loss 2.041710138320923
- `gemma2` on `mentalchat16k`: 341.1 min, final train loss 0.7506640664923359, best eval loss 0.7869569659233093
- `llama32` on `mentalchat16k`: 172.8 min, final train loss 1.0094265091529677, best eval loss 0.996471643447876
- `qwen3` on `mentalchat16k`: 279.0 min, final train loss 0.8965833206929003, best eval loss 0.8896248936653137

> ⚠ Raw reference-based scores from the two test sets are not directly comparable (reference style and length differ between datasets). Use the per-dataset rankings and the tuned-vs-base Δ for cross-dataset conclusions.
