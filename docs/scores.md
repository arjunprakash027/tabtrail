# How tabtrail calculates scores

Scores are calculated in 5 places. All code is in `tabtrail/pipeline.py` and `tabtrail/query.py`.

## 1. Attention per event (`pipeline.events`)

Each event gets `attention_s`, the seconds of attention it stands for.

| Event | attention_s | Source of the number |
|---|---|---|
| Page you read | Brave `total_foreground_duration`, capped at 1,800 s | Time the tab was in front. The cap stops music or a tab left open from counting as hours. |
| Search | 30 s, fixed | `SEARCH_S` |
| Chat message you typed | 120 s, fixed | `CHAT_S` |

Pages with less than 10 s in front and less than 10 s open are dropped. Chat messages with fewer than 4 words, or replies such as "continue" or "try again", are dropped.

## 2. Attention per item (`pipeline.items`)

Events with the same line become one item. Age is the number of days from the event to now.

- `attention_s` = sum of the attention of its events.
- `score_h` = sum of attention hours × 0.5^(age ÷ 7). Attention loses half its value every 7 days (`HALF_LIFE_D`).
- `long_h` = the same sum with a 60-day half-life (`LONG_HALF_LIFE_D`). Only the trend uses it.
- `events` = count of its events.

## 3. Topic score (`pipeline.topics`)

- `score` = sum of `score_h` of its items.
- `attention_h` = all attention ÷ 3,600, with no decay. It is for information only.

Example: one topic has 1 h today, 2 h 14 days ago and 4 h 60 days ago.

```text
score = 1×1 + 2×0.5^(14÷7) + 4×0.5^(60÷7)
      = 1 + 0.5 + 0.01
      = 1.51
```

## 4. Trend (`pipeline.RISING`, `pipeline.FADING`)

The trend compares two averages in hours per day: a short one (7-day half-life) and a long one (60-day half-life).

```text
trend_ratio = (score ÷ window(7)) ÷ (long ÷ window(60))
window(h)   = h ÷ ln 2 × (1 − 0.5^(span ÷ h))
```

`span` is the number of days from the oldest event in the data to now. The window makes steady attention give a ratio of 1, also when the history is short.

| trend_ratio | Trend |
|---|---|
| 1.25 or more | rising |
| more than 0.8, less than 1.25 | steady |
| 0.8 or less | fading |

Both `profile.md` and the query commands use these values.

## 5. Match a new text (`query.match`)

Nothing is saved.

1. Embed the text with the same model and prefix as the pipeline.
2. Similarity = cosine of the new vector and each topic centre.
3. The text joins the closest topic if its similarity is equal to or more than that topic's own 10th percentile (`sim_p10`). If not, the text is a "new" bucket.
4. `interest_score` = the score of the topic it joins, or 0 for a new bucket.

## Known limits

- The fixed 30 s and 120 s values are guesses. They give chat topics more weight than a short page visit.
- The 7-day and 60-day half-lives and the 1.25 and 0.8 cutoffs are first choices.
