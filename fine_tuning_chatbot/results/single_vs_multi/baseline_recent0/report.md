# Single-agent vs Multi-agent — multi-turn CEHS evaluation

10 counsel-chat conversations replayed teacher-forced (60 client turns); both arms use the same tuned gemma2. Replies scored per turn on the SoulChat CEHS rubric (Table 2, arXiv:2311.00273) by glm-4.7-flash.

## CEHS scores (means; content/empathy/helpfulness 0-2, safety 0-1, total 0-7)

| system          |   judged |   missing |   content |   empathy |   helpfulness |   safety |   total |   avg_words |
|:----------------|---------:|----------:|----------:|----------:|--------------:|---------:|--------:|------------:|
| pipeline_single |       60 |         0 |     1.983 |     1.367 |         1.383 |        1 |   5.733 |        48.6 |
| pipeline_multi  |       60 |         0 |     1.883 |     1.383 |         1.117 |        1 |   5.383 |        46.2 |

## Pipeline behavior (multi only)

- escalated turns: 0/60 — these received the app's fixed crisis message
- memory: the multi chatbot saw ONLY the summarizer's compression of the prior turns; the single agent saw the verbatim history

## Diagnosed emotions across turns

- Stress: 29
- Anxiety: 23
- Normal: 3
- Bipolar: 3
- Suicidal: 2

## Notes

- Teacher-forced replay: at every client turn both systems answer the dataset's own context, so scores are paired per turn.
- Prompts, thresholds, crisis message/regex, and the summarizer identity come from the app itself (evaluate/single_vs_multi.py).
- The trimmed composed prompt has no {diagnostic_label} placeholder, so diagnosis affects the multi arm via crisis routing only.