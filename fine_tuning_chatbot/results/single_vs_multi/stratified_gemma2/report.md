# Single-agent vs Multi-agent — multi-turn CEHS evaluation

10 counsel-chat conversations replayed teacher-forced (60 client turns); both arms use the same tuned gemma2. Replies scored per turn on the SoulChat CEHS rubric (Table 2, arXiv:2311.00273) by glm-4.7-flash.

## CEHS scores (means; content/empathy/helpfulness 0-2, safety 0-1, total 0-7)

| system          |   judged |   missing |   content |   empathy |   helpfulness |   safety |   total |   avg_words |
|:----------------|---------:|----------:|----------:|----------:|--------------:|---------:|--------:|------------:|
| pipeline_single |       60 |         0 |     1.983 |     1.35  |         1.3   |        1 |   5.633 |        51   |
| pipeline_multi  |       60 |         0 |     1.983 |     1.283 |         1.333 |        1 |   5.6   |        51.2 |

## CEHS total by case category

| category   |   single |   multi |
|:-----------|---------:|--------:|
| Anxiety    |     5.67 |    5.83 |
| Bipolar    |     5.58 |    5.33 |
| Depression |     5.17 |    5.17 |
| Stress     |     5.67 |    5.67 |
| Suicidal   |     6.08 |    6.08 |

## Pipeline behavior (multi only)

- escalated turns: 0/60 — these received the app's fixed crisis message
- memory: the multi chatbot saw ONLY the summarizer's compression of the prior turns; the single agent saw the verbatim history

## Diagnosed emotions across turns

- Stress: 32
- Anxiety: 20
- Suicidal: 4
- Bipolar: 2
- Depression: 1
- Personality disorder: 1

## Notes

- Teacher-forced replay: at every client turn both systems answer the dataset's own context, so scores are paired per turn.
- Prompts, thresholds, crisis message/regex, and the summarizer identity come from the app itself (evaluate/single_vs_multi.py).
- The trimmed composed prompt has no {diagnostic_label} placeholder, so diagnosis affects the multi arm via crisis routing only.