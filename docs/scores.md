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

Events with the same line become one item.

- `attention_s` = sum of the attention of its events.
- `recent_s` = the same sum for events less than 14 days older than the newest event.
- `events` = count of its events.

## 3. Topic score (`pipeline.topics`)

- `attention_h` = sum of item attention ÷ 3,600.
- `score` = `attention_h` + `events` ÷ 120. 120 events count the same as 1 hour of attention.
- `recent_share` = sum of `recent_s` ÷ sum of `attention_s`.

Example from the demo data, topic 6 "lifetimes ownership traits async": 2.23 h + 40 ÷ 120 = 2.23 + 0.33 = **2.56**.

## 4. Trend (`pipeline.RISING`, `pipeline.STEADY`)

Both `profile.md` and the query commands use these two values.

| recent_share | Trend |
|---|---|
| 0.50 or more | rising |
| 0.15 to 0.49 | steady |
| less than 0.15 | fading |

## 5. Match a new text (`query.match`)

Nothing is saved.

1. Embed the text with the same model and prefix as the pipeline.
2. Similarity = cosine of the new vector and each topic centre.
3. The text joins the closest topic if its similarity is equal to or more than that topic's own 10th percentile (`sim_p10`). If not, the text is a "new" bucket.
4. `interest_score` = the score of the topic it joins, or 0 for a new bucket.

## Known limits

- The fixed 30 s and 120 s values are guesses. They give chat topics more weight than a short page visit.
- `score` adds hours and counts. A different formula is planned.
- Trend uses one window (14 days) from the newest event, not from today.
