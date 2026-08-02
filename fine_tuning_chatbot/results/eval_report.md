# Evaluation Report — Counselor Fine-Tuning Study (3 models x MentalChat16K, reply-only training)

All systems answer the SAME held-out MentalChat16K test split; the stored generations in `results/generations/` are also the input to the LLM-judge evaluation.

## Scores

| model   | variant   |    n |   bertscore_f1 |   bleu |   rouge_l |   flesch_reading_ease |
|:--------|:----------|-----:|---------------:|-------:|----------:|----------------------:|
| gemma2  | tuned     | 1470 |         0.8839 | 0.0867 |    0.2366 |                 45.3  |
| gemma2  | base      | 1470 |         0.849  | 0.0369 |    0.174  |                 50.11 |
| llama32 | tuned     | 1470 |         0.8814 | 0.0835 |    0.227  |                 44.15 |
| llama32 | base      | 1470 |         0.8561 | 0.044  |    0.177  |                 51.16 |
| qwen3   | tuned     | 1470 |         0.8836 | 0.0858 |    0.2351 |                 44.88 |
| qwen3   | base      | 1470 |         0.8519 | 0.0377 |    0.1721 |                 54.43 |

## Winners (tuned models)

- **bertscore_f1**: gemma2 (0.8839)
- **bleu**: gemma2 (0.0867)
- **rouge_l**: gemma2 (0.2366)

## Fine-tuning lift (tuned - base, BERTScore F1)

| model   |   bertscore_f1_base |   bertscore_f1_tuned |   delta_bertscore |
|:--------|--------------------:|---------------------:|------------------:|
| gemma2  |              0.849  |               0.8839 |            0.0349 |
| llama32 |              0.8561 |               0.8814 |            0.0253 |
| qwen3   |              0.8519 |               0.8836 |            0.0317 |

## Training manifests

- `gemma2`: 343.8 min, final train loss 0.7284600630624514, best eval loss 0.7511275410652161
- `llama32`: 165.2 min, final train loss 0.8772237960901638, best eval loss 0.8733553886413574
- `qwen3`: 270.4 min, final train loss 0.8720195713444863, best eval loss 0.8591079711914062