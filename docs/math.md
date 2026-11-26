# The maths inside tabtrail

The examples below come from the [demo data](../examples/demo_history.py) (320 items, 8 topics). The demo dates count back from the day you make it, so your numbers can differ a little.

```
text ──embed──► 768 numbers ──UMAP──► 10 numbers ──HDBSCAN──► topic or no topic
                                                        │
          attention seconds ──sum──► item ──sum──► topic score, trend
                                                        │
                          new text ──embed──► compare to topic centres ──► match
```

## 1. Embedding: text becomes 768 numbers

`nomic-embed-text` reads a line of text and returns a vector: a list of 768 numbers. Text with a similar meaning gets a similar list.

"rust borrow checker" starts `[0.058, 0.013, -0.221, -0.006, 0.066, …]`.

The vector has length 1: √(x₁² + x₂² + … + x₇₆₈²) = 1.00. Ollama already returns it this way. The code divides by the length again to be safe.

### Cosine similarity

Two vectors **a** and **b** of length 1 have similarity:

  sim(a, b) = a₁b₁ + a₂b₂ + … + a₇₆₈b₇₆₈

This is the cosine of the angle between them. A larger number means a closer direction.

| Pair | Similarity |
|---|---|
| "rust borrow checker" and "how does the rust borrow checker work" | **0.965** |
| "rust borrow checker" and "Rust ownership explained" | 0.822 |
| "how does the rust borrow checker work" and "Rust ownership explained" | 0.822 |
| "rust borrow checker" and "Best sourdough bread recipe" | 0.644 |
| "how does the rust borrow checker work" and "Best sourdough bread recipe" | 0.596 |
| "Rust ownership explained" and "Best sourdough bread recipe" | **0.576** |

Unrelated text still scores about 0.6 with this model, not 0. So a fixed cut such as "0.5 means related" is wrong. tabtrail uses cuts that come from the data (section 7).

## 2. Why the 768 numbers are not clustered directly

In 768 dimensions, most pairs of points are at almost the same distance. "Dense" and "sparse" become hard to tell apart. In one test on a real history, HDBSCAN on the 768 numbers put 4,476 of 5,545 items in one topic.

## 3. UMAP: 768 numbers become 10

UMAP keeps who is near whom and drops the rest.

**Step 1. Find neighbours.** For each item, UMAP finds its 15 nearest items (`n_neighbors=15`) by cosine. The 5 nearest to "A beginner guide to ownership" (topic 6):

| Neighbour | Similarity | Topic |
|---|---|---|
| ownership tutorial | 0.938 | 6 |
| best way to learn ownership | 0.928 | 6 |
| How ownership works | 0.908 | 6 |
| Ownership explained | 0.906 | 6 |
| ownership | 0.901 | 6 |

**Step 2. Weight each link.** The link from item *i* to neighbour *j* gets a weight:

  w(i→j) = exp(−(d(i,j) − ρᵢ) / σᵢ)

- d(i,j) is the distance (1 − cosine).
- ρᵢ is the distance to the nearest neighbour of *i*. So the nearest neighbour always gets weight 1.
- σᵢ is chosen so that the 15 weights of *i* add up to log₂(15) ≈ 3.9. Items in a crowded area and items in an empty area get the same total pull.

The two directions are joined: w = w(i→j) + w(j→i) − w(i→j)·w(j→i).

**Step 3. Lay the points out in 10 dimensions.** UMAP starts from a rough layout and moves the points step by step. Linked points pull together. Random unlinked points push apart. It stops when the layout keeps the links best (it minimizes the cross-entropy between the two sets of links).

`min_dist=0.0` lets close points sit on top of each other. That makes tight groups, which suits clustering.

"A beginner guide to ownership" ends at `[10.72, 4.02, 4.54, 8.34, 3.16, …]`. The 10 numbers have no meaning alone. Only distances between points matter.

## 4. HDBSCAN: find dense groups, leave the rest out

Settings: `min_samples=5`, `min_cluster_size=15`.

**Core distance.** The distance from a point to its 5th nearest neighbour. Small means the point sits in a crowd.

| Item (distances in the 10 UMAP numbers) | Core distance |
|---|---|
| A beginner guide to ownership (topic 6) | 0.058 |
| best way to learn iterators (no topic) | 0.249 |
| Median, items with a topic | 0.110 |
| Median, items with no topic | 0.107 |

The demo titles follow a few templates, so they form many small, tight groups. For that reason the two medians are almost equal. A group with fewer than 15 items gets no topic, even if it is tight. In a test on a real history, the medians were 0.086 with a topic and 0.240 without.

**Mutual reachability distance.** HDBSCAN replaces the plain distance between a and b with:

  mr(a, b) = max( d(a,b), core(a), core(b) )

Example: "A beginner guide to ownership" and "ownership tutorial" are 0.018 apart. Their core distances are 0.058 and 0.076. So mr = max(0.018, 0.058, 0.076) = **0.076**. A point in a sparse area stays far from everything, even from a close neighbour. That stops lone points from joining groups.

**The tree.** HDBSCAN joins all points with the shortest set of links (a minimum spanning tree on mr). Then it removes links from the longest to the shortest. The tree breaks into groups.

- A break counts only if both parts have at least 15 items. Otherwise, the small part "falls out" as noise.
- HDBSCAN keeps the groups that last longest while links are removed. It measures this with λ = 1 / distance: stability = sum over points of (λ when the point leaves − λ when the group starts).
- Points that never belong to a stable group get topic −1: no topic. In the demo, that was 34% of items.

## 5. Topic words: TF-IDF

For the items in one topic:

- tf(word, item) = how many times the word is in the item.
- idf(word) = ln((1 + N) / (1 + df)) + 1. N is the number of items in the topic. df is how many of them contain the word. Rare words get a higher idf.
- Each item's scores are scaled so that the item has length 1. Then the scores are summed over all items.

Topic 6 (40 items):

| Word | Summed score | idf |
|---|---|---|
| lifetimes | 5.65 | 2.32 |
| ownership | 5.65 | 2.32 |
| traits | 5.65 | 2.32 |
| async | 4.82 | 2.32 |
| await | 4.82 | 2.32 |

The top 4 words become the label: "lifetimes ownership traits async".

Weakness: idf is counted inside the topic only. A word that is common everywhere, such as "google", can still win. The fix is class-based TF-IDF, which counts idf across all topics.

## 6. Attention and scores

**Per event** (`attention_s`):

| Event | Seconds |
|---|---|
| Page | time the tab was in front, at most 1,800 |
| Search | 30, fixed |
| Chat message | 120, fixed |

**Per item:** attention = sum over its events. recent = the same sum for events less than 14 days older than the newest event. events = count.

**Per topic:**

  attention_h = Σ attention / 3,600
  score = attention_h + events / 120
  recent_share = Σ recent / Σ attention

Topic 6: attention_h = 2.23, events = 40.
score = 2.23 + 40 / 120 = 2.23 + 0.33 = **2.56**. recent_share = 0.79.

**Trend:** recent_share ≥ 0.50 is rising, ≥ 0.15 is steady, less is fading. Topic 6 is rising.

The `events / 120` part gives each event 30 s more. A search or a chat message then counts twice. This part is planned for removal.

## 7. Matching new text

**Topic centre.** The mean of the topic's vectors, scaled back to length 1:

  c = (v₁ + v₂ + … + vₙ) / ‖v₁ + v₂ + … + vₙ‖

**How close the topic's own items are.** For topic 6, the similarity of each of its 40 items to c:

| min | 10th percentile | median | max |
|---|---|---|---|
| 0.819 | **0.828** | 0.848 | 0.870 |

**Rule.** New text joins its closest topic if sim(new, c) ≥ that topic's 10th percentile. For topic 6, the cut is 0.828. About 90% of the topic's own items pass it.

Examples: "sourdough starter feeding schedule" scored 0.923 against a cut of 0.911. It joined topic 7. "How to repot a monstera plant" scored 0.742 at best against a cut of 0.854. It became a new topic. "how do rust lifetimes work" scored 0.810 against the cut of 0.828. It did not join, although it is about Rust.

This rule uses the 768 numbers, not the 10 from UMAP. A new point cannot go through UMAP and HDBSCAN without a full rerun. The centre test is a fast stand-in. It assumes a topic is round around its centre. A long, thin topic can reject text that HDBSCAN would accept.

## 8. Known weak points

1. 30 s for a search and 120 s for a chat message are fixed guesses.
2. `events / 120` counts searches and chat messages twice.
3. Topic words use idf inside one topic, not across all topics.
4. The 14-day window ends at the newest event, not at today.
5. Matching assumes round topics.
6. UMAP and HDBSCAN use a fixed seed. Another seed gives slightly different topics.
