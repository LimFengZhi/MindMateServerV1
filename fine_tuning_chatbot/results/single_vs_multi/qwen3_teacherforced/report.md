# Single-agent vs Multi-agent — multi-turn CEHS evaluation

10 counsel-chat conversations replayed teacher-forced (60 client turns); both arms use the same tuned qwen3. Replies scored per turn on the SoulChat CEHS rubric (Table 2, arXiv:2311.00273) by glm-4.7-flash.

## CEHS scores (means; content/empathy/helpfulness 0-2, safety 0-1, total 0-7)

| system          |   judged |   missing |   content |   empathy |   helpfulness |   safety |   total |   avg_words |
|:----------------|---------:|----------:|----------:|----------:|--------------:|---------:|--------:|------------:|
| pipeline_single |       60 |         0 |     1.933 |     1.25  |         1.317 |        1 |   5.5   |        67.2 |
| pipeline_multi  |       60 |         0 |     1.983 |     1.233 |         1.25  |        1 |   5.467 |        62.6 |

## CEHS total by case category

| category   |   single |   multi |
|:-----------|---------:|--------:|
| Anxiety    |     5.33 |    5.67 |
| Bipolar    |     4.92 |    5.33 |
| Depression |     5.42 |    5.08 |
| Stress     |     5.61 |    5.39 |
| Suicidal   |     6.08 |    6    |

## Pipeline behavior (multi only)

- escalated turns: 0/60 — these received the app's fixed crisis message
- memory: the multi chatbot saw the last 2 exchanges verbatim + the summarizer's compression of older turns (the app's hybrid memory); the single agent saw the full verbatim history

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