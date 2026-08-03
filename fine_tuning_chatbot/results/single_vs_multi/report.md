# Single-agent vs Multi-agent — multi-turn CEHS evaluation

10 counsel-chat conversations replayed teacher-forced (60 client turns, free-running: scripted client, each arm's OWN replies as history); both arms use the same tuned qwen3. Replies scored per turn on the SoulChat CEHS rubric (Table 2, arXiv:2311.00273) by glm-4.7-flash.

## CEHS scores (means; content/empathy/helpfulness 0-2, safety 0-1, total 0-7)

| system          |   judged |   missing |   content |   empathy |   helpfulness |   safety |   total |   avg_words |
|:----------------|---------:|----------:|----------:|----------:|--------------:|---------:|--------:|------------:|
| pipeline_single |       60 |         0 |     1.75  |     1.217 |         1.267 |        1 |   5.233 |       104   |
| pipeline_multi  |       60 |         0 |     1.817 |     1.3   |         1.267 |        1 |   5.383 |        85.9 |

## CEHS total by case category

| category   |   single |   multi |
|:-----------|---------:|--------:|
| Anxiety    |     6.17 |    6.33 |
| Bipolar    |     5.17 |    5    |
| Depression |     5    |    5.17 |
| Stress     |     5.06 |    5.28 |
| Suicidal   |     5.33 |    5.67 |

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

- Free-running replay: the client side is scripted, but each arm answers with ITS OWN prior replies as history (the dataset's counselor replies are unused) — deployment-realistic; turns are paired by position, not by identical context.
- Prompts, thresholds, crisis message/regex, and the summarizer identity come from the app itself (evaluate/single_vs_multi.py).
- The trimmed composed prompt has no {diagnostic_label} placeholder, so diagnosis affects the multi arm via crisis routing only.