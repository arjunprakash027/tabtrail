"""Command line. --json on any command prints JSON, so AI agents can run and read it."""
import argparse, json, sys, time
from . import config, db

STEPS = ["ingest", "events", "normalized", "items", "embeddings", "clusters", "topics", "profile_md"]

def build():
    from hamilton import driver
    from . import pipeline
    return driver.Builder().with_modules(pipeline).build()

def summarize(v):
    import numpy as np, pandas as pd
    if isinstance(v, pd.DataFrame): return {"rows": len(v), **({"llm_lines": v.attrs["llm_lines"]} if "llm_lines" in v.attrs else {}), **({"run_id": v.attrs["run_id"]} if "run_id" in v.attrs else {})}
    if isinstance(v, np.ndarray):
        if v.ndim == 1: return {"topics": int(len(set(v.tolist()) - {-1})), "no_topic_share": round(float((v < 0).mean()), 2) if len(v) else 0.0}
        return {"shape": list(v.shape)}
    return v

def run(cfg, to):
    con = db.connect(cfg); dr = build()
    want = STEPS[: STEPS.index(to) + 1]
    t0 = time.time(); res = dr.execute(want, inputs={"cfg": cfg, "con": con}); con.close()
    out = {k: summarize(res[k]) for k in want}; out["seconds"] = round(time.time() - t0, 1)
    con = db.connect(cfg)
    run_id = out.get("topics", {}).get("run_id")   # same id as the topics it made; a new id when no topics were written
    con.execute("INSERT INTO runs VALUES (coalesce(?, nextval('run_seq')), ?, ?)", [run_id, int(time.time()), json.dumps(out, default=str)]); con.close()
    return out

def main(argv=None):
    p = argparse.ArgumentParser(prog="tabtrail", description="Turn your browser history and AI chats into a map of your interests. All local.")
    p.add_argument("--json", action="store_true", help="print JSON (for scripts and AI agents)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the pipeline: " + " -> ".join(STEPS)); r.add_argument("--to", choices=STEPS, default=STEPS[-1], help="stop after this step")
    sub.add_parser("graph", help="list each step and the steps it needs")
    i = sub.add_parser("interests", help="interests from the latest run")
    i.add_argument("--mode", choices=["top", "recent", "rising", "fading"], default="top"); i.add_argument("--source", choices=["brave", "claude", "pi"])
    i.add_argument("--limit", type=int, default=10)
    t = sub.add_parser("topic", help="one topic and its top items"); t.add_argument("topic_id", type=int); t.add_argument("--limit", type=int, default=15)
    m = sub.add_parser("match", help="which topic new text would join (nothing is saved)")
    m.add_argument("--kind", required=True, choices=["search", "page", "chat"]); m.add_argument("--text", required=True); m.add_argument("--mlx", action="store_true", help="summarize long chat text with the local model first")
    sub.add_parser("last-run", help="when the pipeline last ran, and whether it should run again")
    sub.add_parser("profile", help="print profile.md")
    sub.add_parser("status", help="what is stored")
    a = p.parse_args(argv); cfg = config.load()
    if a.cmd == "run": out = run(cfg, a.to)
    elif a.cmd == "graph":
        dr = build()
        out = {v.name: sorted(v.required_dependencies) for v in dr.list_available_variables() if v.name in STEPS}
    elif a.cmd == "profile": print(cfg.profile_md.read_text()); return
    else:
        from . import query
        try:
            out = {"interests": lambda: query.interests(cfg, a.mode, a.source, a.limit), "topic": lambda: query.topic(cfg, a.topic_id, a.limit),
                   "match": lambda: query.match(cfg, a.kind, a.text, a.mlx), "last-run": lambda: query.last_run(cfg),
                   "status": lambda: query.status(cfg)}[a.cmd]()
        except query.Busy as e: out = {"error": str(e)}
    if a.json or a.cmd != "interests": print(json.dumps(out, indent=1, default=str))
    else:
        for r in out: print(f"{r['rank']:>4}. topic {r['topic_id']:<4} score {r['score']:>6}  trend {r['trend_ratio']:>5} {r['trend']:<7} {r['sources']:<16} {r['words']}")

if __name__ == "__main__": main()
