"""The pipeline as a Hamilton graph. Each function is one step; its arguments name the steps it needs.
Run it with: tabtrail run   (or tabtrail run --to events, to stop early)
"""
import json, re, time, urllib.request
import numpy as np
import pandas as pd
import duckdb
from . import adapters
from .config import Config

# ---------- 1 · ingest: each source adds new raw rows ----------
def ingest(cfg: Config, con: duckdb.DuckDBPyConnection) -> dict:
    return {s: adapters.ALL[s](cfg, con) for s in cfg.sources}

# ---------- 2 · events: one row shape for every source ----------
DROP_HOST = re.compile(r"^(mail\.google|accounts\.|login\.|auth\.|localhost|127\.0\.0\.1|calendar\.google|.*\.okta\.com)")
SUFFIX = re.compile(r"\s*[-|–—·•:]\s*(YouTube Music|YouTube|Google Search|Google Docs|Google Slides|Google Sheets|Google Drive|"
                    r"LinkedIn|GitHub|Claude|ChatGPT|Gemini|Google Gemini|Reddit|Medium|Stack Overflow|Wikipedia|X|Hacker News|"
                    r"LeetCode|HackerRank|Notion|ClickUp|Gmail|Brave Search|Perplexity|Amazon\.[a-z.]+|eBay)\s*$", re.I)
BRAND_ONLY = re.compile(r"^(youtube( music)?|linkedin|claude|chatgpt|google( gemini)?|gemini|github|new tab|inbox.*|untitled|loading.*|"
                        r"sign in.*|log in.*|login.*|register.*|settings|overview|pricing|search \| linkedin|feed|home|notifications|messaging)$", re.I)
SEARCH_S, CHAT_S = 30.0, 120.0   # attention seconds for a search and a typed message (first guess)
MAX_PAGE_S = 1800.0              # one visit counts at most 30 min: music or a tab left in front is not 3 hours of attention
LONG_WORDS, LINE_WORDS = 25, 30   # a chat message with more words than LONG_WORDS becomes one line
HALF_LIFE_D, LONG_HALF_LIFE_D = 7, 60   # attention counts half after this many days (score, and the long average for trend)
RISING, FADING = 1.25, 0.8        # trend ratio at or above RISING: rising; at or below FADING: fading
MIN_ITEMS = 50                    # fewer items: no clustering, so no topics
ACK = re.compile(r"^(yes|yep|ya|ok|okay|no|done|continue|go|go on|try again|try now|thanks|thank you|nice|cool|great|perfect|sure|lets go|let's go)\b.{0,20}$", re.I)

def _clean_title(t: str) -> str:
    t = re.sub(r"^\(\d+\)\s*", "", (t or "").strip())
    for _ in range(2): t = SUFFIX.sub("", t).strip()
    return t

def events(ingest: dict, cfg: Config, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """source, ts, kind, text, context, location, attention_s"""
    b = con.execute("select * from brave_visits").df()
    b = b[~b["host"].str.match(DROP_HOST)]
    s = b[b["search_term"].notna()]
    searches = pd.DataFrame({"source": "brave", "ts": s.ts, "kind": "search", "text": s.search_term.str.strip().str.lower(),
                             "context": s.host, "location": s.url, "attention_s": SEARCH_S})
    p = b[b["search_term"].isna()].copy()
    p["text"] = p["title"].map(_clean_title)
    p = p[(p.text.str.len() >= 6) & ~p.text.str.match(BRAND_ONLY)]
    p = p[(p.focus_s.fillna(0) >= cfg.min_seconds) | (p.open_s.fillna(0) >= cfg.min_seconds)]
    pages = pd.DataFrame({"source": "brave", "ts": p.ts, "kind": "page", "text": p.text, "context": p.host,
                          "location": p.url, "attention_s": p.focus_s.fillna(0).clip(upper=MAX_PAGE_S)})
    c = con.execute("select * from chat_messages").df()
    c = c[(c.text.str.split().str.len() >= 4) & ~c.text.str.strip().str.match(ACK)]   # "continue", "try again": replies, not interests
    chats = pd.DataFrame({"source": c.source, "ts": c.ts, "kind": "chat", "text": c.text, "context": c.cwd,
                          "location": c.location, "attention_s": CHAT_S})
    out = pd.concat([searches, pages, chats], ignore_index=True)
    return out[out.ts.notna()].sort_values("ts").reset_index(drop=True)

# ---------- 3 · normalize: one short line per event ----------
def _first_words(t: str) -> str: return " ".join(t.split()[:LINE_WORDS])
def _trend(r: float) -> str: return "rising" if r >= RISING else ("fading" if r <= FADING else "steady")

def _long(events: pd.DataFrame) -> pd.Series:
    return (events.kind == "chat") & (events.text.str.split().str.len() > LONG_WORDS)

def _with_lines(events: pd.DataFrame, cache: dict) -> pd.DataFrame:
    """Adds 'line': short text stays; a long chat message gets its cached line, or its first words."""
    out = events.copy(); long = _long(out)
    out["line"] = out.text
    out.loc[long, "line"] = out.loc[long, "text"].map(lambda t: cache.get(t) or _first_words(t))
    return out

def _embed(cfg: Config, texts: list, timeout: int = 300) -> list:
    req = urllib.request.Request(cfg.ollama + "/api/embed", method="POST", headers={"content-type": "application/json"},
        data=json.dumps({"model": cfg.embed_model, "input": ["clustering: " + t for t in texts]}).encode())
    return json.load(urllib.request.urlopen(req, timeout=timeout))["embeddings"]

_llm = {}
def _mlx_line(cfg, text):
    if "m" not in _llm:
        from mlx_lm import load
        _llm["m"] = load(cfg.llm_model)
    from mlx_lm import generate
    model, tok = _llm["m"]
    p = tok.apply_chat_template([{"role": "user", "content": "Rewrite what the user was after as one short line, at most 12 words, "
        "like a search query. Output only the line.\n\nText: " + text[:2000]}], add_generation_prompt=True, tokenize=False, enable_thinking=False)
    return generate(model, tok, prompt=p, max_tokens=30).strip().strip('"')

def normalized(events: pd.DataFrame, cfg: Config, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Adds 'line': short text stays; a long chat message gets one line from a local LLM (cached), or its first 30 words."""
    long = _long(events)
    cached = dict(con.execute("select text_in, line from lines").fetchall())   # a line from any model is reused
    todo = [t for t in events.loc[long, "text"].unique() if t not in cached]
    made = 0
    if cfg.lines == "mlx":
        for t in todo[:cfg.lines_per_run]:
            line = _mlx_line(cfg, t); cached[t] = line; made += 1
            con.execute("INSERT OR REPLACE INTO lines VALUES (?,?,?)", [t, cfg.llm_model, line])
    out = _with_lines(events, cached)
    out.attrs["llm_lines"] = {"new": made, "waiting": max(0, len(todo) - made)}
    return out

# ---------- 4 · items: same line from many events becomes one item ----------
def _decayed_h(attention_s: pd.Series, ts: pd.Series, half_life_d: float) -> pd.Series:
    """Hours of attention, halved for each half_life_d days of age (age from now)."""
    age_d = ((time.time() - ts) / 86400).clip(lower=0)
    return attention_s * 0.5 ** (age_d / half_life_d) / 3600

def _window_d(span_d: float, half_life_d: float) -> float:
    """Total weight of one day of attention per day across span_d days, so steady attention gives a trend ratio of 1."""
    return half_life_d / np.log(2) * (1 - 0.5 ** (span_d / half_life_d))

def items(normalized: pd.DataFrame) -> pd.DataFrame:
    g = normalized.assign(score_h=_decayed_h(normalized.attention_s, normalized.ts, HALF_LIFE_D),
                          long_h=_decayed_h(normalized.attention_s, normalized.ts, LONG_HALF_LIFE_D)).groupby("line")
    return pd.DataFrame({"events": g.size(), "attention_s": g.attention_s.sum(), "score_h": g.score_h.sum(), "long_h": g.long_h.sum(),
                         "first_ts": g.ts.min(), "last_ts": g.ts.max(), "sources": g.source.agg(lambda s: ",".join(sorted(set(s)))),
                         "kind": g.kind.first()}).reset_index().rename(columns={"line": "text"})

# ---------- 5 · embed (cached by text) ----------
def embeddings(items: pd.DataFrame, cfg: Config, con: duckdb.DuckDBPyConnection) -> np.ndarray:
    if items.empty: return np.empty((0, 0), dtype=np.float32)
    have = {t for (t,) in con.execute("select text from embeddings where model=?", [cfg.embed_model]).fetchall()}
    todo = [t for t in items.text if t not in have]
    for i in range(0, len(todo), 128):
        part = todo[i:i+128]
        vecs = _embed(cfg, part)
        con.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?,?)", [(t, cfg.embed_model, v) for t, v in zip(part, vecs)])
    m = dict(con.execute("select text, vec from embeddings where model=?", [cfg.embed_model]).fetchall())
    X = np.array([m[t] for t in items.text], dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    return X

# ---------- 6 · cluster: UMAP to 10 numbers, then HDBSCAN; -1 means no topic ----------
def clusters(embeddings: np.ndarray) -> np.ndarray:
    if len(embeddings) < MIN_ITEMS: return np.full(len(embeddings), -1)   # too few items to cluster
    import umap
    from sklearn.cluster import HDBSCAN
    Z = umap.UMAP(n_components=10, n_neighbors=15, min_dist=0.0, metric="cosine", random_state=0).fit_transform(embeddings)
    return HDBSCAN(min_cluster_size=15, min_samples=5, copy=True).fit_predict(Z)

# ---------- 7 · topics: totals, top words, score, trend ----------
TOPIC_COLS = ["topic_id", "words", "items", "events", "attention_h", "trend_ratio", "score", "sources", "examples"]
RUN_TABLES = ("topics", "topic_centroids", "topic_items")

def topics(items: pd.DataFrame, clusters: np.ndarray, embeddings: np.ndarray, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    from sklearn.feature_extraction.text import TfidfVectorizer
    df = items.assign(topic=clusters)
    span_d = (time.time() - items.first_ts.min()) / 86400 if len(items) else 0.0   # days of history in the data
    rows = []
    for k, g in df[df.topic >= 0].groupby("topic"):
        try:
            tf = TfidfVectorizer(stop_words="english", token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9+#.-]{2,}\b").fit(g.text)
            sc = np.asarray(tf.transform(g.text).sum(axis=0)).ravel()
            words = " ".join(w for w, _ in sorted(zip(tf.get_feature_names_out(), sc), key=lambda x: -x[1])[:4])
        except ValueError: words = ""
        score, long = g.score_h.sum(), g.long_h.sum()
        rows.append({"topic_id": int(k), "words": words, "items": len(g), "events": int(g.events.sum()),
                     "attention_h": round(g.attention_s.sum() / 3600, 2),
                     # short average ÷ long average, each in hours per day over the history that exists
                     "trend_ratio": round((score / _window_d(span_d, HALF_LIFE_D)) / (long / _window_d(span_d, LONG_HALF_LIFE_D)), 2) if long else 0.0,
                     "score": round(score, 3),
                     "sources": ",".join(sorted(set(",".join(g.sources).split(",")))),
                     "examples": " | ".join(g.sort_values("attention_s", ascending=False).text.head(5))})
    t = pd.DataFrame(rows, columns=TOPIC_COLS).sort_values("score", ascending=False).reset_index(drop=True)
    if t.empty: return t   # no topics: write nothing, so the last run stays as it is
    # centroid of each topic + how close its own members sit to it: used by 'tabtrail match' to place new text
    cents = []
    for k in t.topic_id:
        V = embeddings[clusters == k]; c = V.mean(0); c /= np.linalg.norm(c); s = V @ c
        cents.append((int(k), c.tolist(), float(np.percentile(s, 10)), float(np.median(s))))
    con.begin()   # one run is written whole or not at all
    try:
        run_id = con.execute("select nextval('run_seq')").fetchall()[0][0]
        con.register("t", t.assign(run_id=run_id))
        con.execute(f"INSERT INTO topics BY NAME SELECT run_id, {', '.join(TOPIC_COLS)} FROM t")
        con.unregister("t")
        con.executemany("INSERT INTO topic_centroids VALUES (?,?,?,?,?)", [(run_id, *c) for c in cents])
        con.register("ti", df[["text", "topic"]].assign(run_id=run_id))
        con.execute("INSERT INTO topic_items SELECT run_id, text, topic FROM ti")
        con.unregister("ti")
        for tab in RUN_TABLES: con.execute(f"DELETE FROM {tab} WHERE run_id < ?", [run_id])   # only the latest run is read
        con.commit()
    except Exception:
        con.rollback(); raise
    t.attrs["run_id"] = int(run_id)
    return t

# ---------- 8 · profile.md ----------
def profile_md(topics: pd.DataFrame, items: pd.DataFrame, clusters: np.ndarray, cfg: Config) -> str:
    if topics.empty: return str(cfg.profile_md)   # no topics: keep the last profile.md
    lines = [f"# profile.md ({time.strftime('%d %b %Y')})", "", "Made by tabtrail from your local history. Nothing left this machine.", "",
             "## Topics by attention", "", "| # | Topic (top words) | Score | Trend ratio | Trend | Sources |", "|---|---|---|---|---|---|"]
    for i, r in topics.head(25).iterrows():
        lines.append(f"| {i+1} | {r.words} | {r.score} | {r.trend_ratio} | {_trend(r.trend_ratio)} | {r.sources} |")
    lines += ["", f"Items with a topic: {int((clusters >= 0).sum())} of {len(items)}. Without a topic: {int((clusters < 0).sum())}."]
    text = "\n".join(lines) + "\n"
    cfg.profile_md.write_text(text)
    return str(cfg.profile_md)
