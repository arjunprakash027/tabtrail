"""Structured questions over the latest run. Read-only: nothing here changes the database."""
import os, time
import numpy as np
from . import db, pipeline

STALE_HOURS = float(os.environ.get("TABTRAIL_STALE_HOURS", "24"))
TREND = f"CASE WHEN trend_ratio >= {pipeline.RISING} THEN 'rising' WHEN trend_ratio <= {pipeline.FADING} THEN 'fading' ELSE 'steady' END"

class Busy(Exception): pass

def _con(cfg):
    try: return db.connect(cfg, read_only=True)
    except Exception as e:
        if "lock" in str(e).lower(): raise Busy("The pipeline is running. Try again when it finishes.")
        raise

def _latest(con):
    r = con.execute("select max(run_id) from topics").fetchall()[0][0]
    if r is None: raise SystemExit("No topics yet. Run: tabtrail run")
    return r

def status(cfg):
    """How many rows each table holds."""
    con = _con(cfg)
    out = {t: con.execute(f"select count(*) from {t}").fetchall()[0][0] for t in ("brave_visits", "chat_messages", "lines", "embeddings")}
    out["by_source"] = dict(con.execute("select source, count(*) from chat_messages group by 1").fetchall())
    out["db"] = str(cfg.db)
    return out

def last_run(cfg):
    """When the pipeline last finished, and whether there is newer data than that."""
    con = _con(cfg)
    rows = con.execute("select ts from runs where json_extract(stats, '$.profile_md') is not null order by ts desc limit 1").fetchall()
    last = rows[0][0] if rows else None
    newest = {}
    hist = cfg.profile / "History"
    if hist.exists(): newest["brave"] = int(hist.stat().st_mtime)
    for name, d in (("claude", cfg.claude_dir), ("pi", cfg.pi_dir)):
        if d.exists():
            m = max((f.stat().st_mtime for f in d.rglob("*.jsonl")), default=0)
            if m: newest[name] = int(m)
    age_h = round((time.time() - last) / 3600, 1) if last else None
    new_data = [s for s, m in newest.items() if last is None or m > last]
    stale = last is None or age_h > STALE_HOURS
    return {"last_run": time.strftime("%Y-%m-%d %H:%M", time.localtime(last)) if last else None, "age_hours": age_h,
            "stale_after_hours": STALE_HOURS, "stale": stale, "sources_with_new_data": new_data,
            "should_run": bool(stale or new_data), "run_with": "tabtrail run"}

def interests(cfg, mode="top", source=None, limit=10):
    """mode: top (all, by score) | recent (not fading) | rising | fading. Always sorted by score."""
    con = _con(cfg); run = _latest(con)
    where = {"top": "true", "recent": "trend <> 'fading'", "rising": "trend = 'rising'", "fading": "trend = 'fading'"}[mode]
    q = f"""select topic_id, words, score, trend_ratio, {TREND} as trend, items, events,
                   attention_h, sources, rank() over (order by score desc) as rank
            from topics where run_id = ? """
    rows = con.execute(f"select * from ({q}) where {where} {'and sources like ?' if source else ''} order by score desc limit ?",
                       [run] + ([f"%{source}%"] if source else []) + [limit]).df()
    return rows.to_dict("records")

def topic(cfg, topic_id, limit=15):
    """One topic: its numbers and the items in it with the most attention."""
    con = _con(cfg); run = _latest(con)
    t = con.execute(f"select topic_id, words, score, trend_ratio, {TREND} as trend, items, events, attention_h, sources "
                    f"from topics where run_id=? and topic_id=?", [run, topic_id]).df()
    if t.empty: raise SystemExit(f"No topic {topic_id} in the latest run.")
    rank = con.execute("select count(*) + 1 from topics where run_id=? and score > ?", [run, float(t.score[0])]).fetchall()[0][0]
    total = con.execute("select count(*) from topics where run_id=?", [run]).fetchall()[0][0]
    top = con.execute("""select ti.text from topic_items ti where ti.run_id=? and ti.topic_id=?""", [run, topic_id]).fetchall()
    texts = [r[0] for r in top]
    return {**t.to_dict("records")[0], "rank": f"{rank} of {total}", "top_items": _item_stats(cfg, con, texts, limit)}

def _item_stats(cfg, con, texts, limit):
    # per-item numbers are not stored, so rebuild them from the raw tables (read-only, about 2 s)
    import pandas as pd
    lines = dict(con.execute("select text_in, line from lines").fetchall())
    e = pipeline._with_lines(pipeline.events({}, cfg, con), lines)
    e = e[e.line.isin(set(texts))]
    g = e.groupby("line").agg(attention_s=("attention_s", "sum"), events=("ts", "size"), last_seen=("ts", "max"),
                              sources=("source", lambda s: ",".join(sorted(set(s)))), example_location=("location", "first"))
    g = g.sort_values("attention_s", ascending=False).head(limit).reset_index()
    g["last_seen"] = pd.to_datetime(g.last_seen, unit="s").dt.strftime("%Y-%m-%d")
    g["attention_min"] = (g.attention_s / 60).round(1)
    return g.rename(columns={"line": "text"})[["text", "attention_min", "events", "last_seen", "sources", "example_location"]].to_dict("records")

def match(cfg, kind, text, use_mlx=False):
    """Which topic a new piece of text would join (kind: search | page | chat). Nothing is saved."""
    text = (text or "").strip()
    if kind == "search": line = text.lower()
    elif kind == "page":
        line = pipeline._clean_title(text)
        if len(line) < 6 or pipeline.BRAND_ONLY.match(line): raise SystemExit("This page title is too generic to place (for example 'Login' or 'YouTube'). Give the full title.")
    else:
        line = pipeline._mlx_line(cfg, text) if (use_mlx and len(text.split()) > pipeline.LONG_WORDS) else pipeline._first_words(text)
    if len(line) < 2: raise SystemExit("--text is empty.")
    e = np.asarray(pipeline._embed(cfg, [line], timeout=60)[0], dtype=np.float32); e /= np.linalg.norm(e)
    con = _con(cfg); run = _latest(con)
    rows = con.execute(f"""select c.topic_id, c.vec, c.sim_p10, c.sim_median, t.words, t.score, t.trend_ratio, {TREND} as trend, t.examples
                           from topic_centroids c join topics t using(run_id, topic_id) where c.run_id=?""", [run]).fetchall()
    if not rows: raise SystemExit("This run has no topic centroids. Run: tabtrail run")
    sims = np.array([np.asarray(r[1], dtype=np.float32) @ e for r in rows])
    order = np.argsort(-sims)
    ranks = {r[0]: i + 1 for i, r in enumerate(sorted(rows, key=lambda r: -r[5]))}
    def card(i):
        r = rows[i]
        return {"topic_id": r[0], "words": r[4], "similarity": round(float(sims[i]), 3), "joins_if_at_least": round(r[2], 3),
                "score": r[5], "rank": f"{ranks[r[0]]} of {len(rows)}", "trend_ratio": r[6], "trend": r[7], "examples": r[8].split(" | ")[:3]}
    best = card(order[0])
    joins = best["similarity"] >= best["joins_if_at_least"]
    return {"input": {"kind": kind, "text": text[:200], "line_embedded": line},
            "bucket": "existing" if joins else "new",
            "topic": best if joins else None,
            "interest_score": best["score"] if joins else 0.0,
            "nearest": [card(i) for i in order[:3]],
            "how": "Joins a topic when its similarity to the topic centre is at least the 10th percentile of that topic's own items. Nothing is saved."}
