"""One static HTML page of the latest run. It stays in the data folder and loads nothing from the network."""
import json, time
from . import query

COLS = ["topic_id", "words", "score", "trend_ratio", "trend", "items", "events", "attention_h", "sources", "examples"]
TOP_ITEMS = 10

def build(cfg) -> str:
    con = query._con(cfg); run = query._latest(con)
    rows = con.execute(f"select topic_id, words, score, trend_ratio, {query.TREND} as trend, items, events, attention_h, sources, examples "
                       "from topics where run_id=? order by score desc", [run]).fetchall()
    topics = [dict(zip(COLS, r), rank=i + 1, top_items=[]) for i, r in enumerate(rows)]
    by_id = {t["topic_id"]: t for t in topics}
    topic_of = dict(con.execute("select text, topic_id from topic_items where run_id=? and topic_id >= 0", [run]).fetchall())
    for s in query._item_stats(cfg, con, list(topic_of), len(topic_of)):   # sorted by attention, most first
        t = by_id.get(topic_of[s["text"]])
        if t and len(t["top_items"]) < TOP_ITEMS: t["top_items"].append(s)
    data = {"topics": topics, "status": query.status(cfg), "last_run": query.last_run(cfg)["last_run"], "made": time.strftime("%Y-%m-%d %H:%M")}
    path = cfg.home / "dashboard.html"
    path.write_text(_html(data))
    return str(path)

def _html(data: dict) -> str:
    # titles come from the web: escape "<" so no text can close the script block
    return PAGE.replace("__DATA__", json.dumps(data, default=str).replace("<", "\\u003c"))

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>tabtrail dashboard</title>
<style>
:root{--bg:#fafaf9;--fg:#1c1917;--mute:#78716c;--line:#e7e5e4;--card:#fff;--bar:#6366f1;--up:#15803d;--flat:#a16207;--down:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#0c0a09;--fg:#e7e5e4;--mute:#a8a29e;--line:#292524;--card:#1c1917;--bar:#818cf8;--up:#4ade80;--flat:#facc15;--down:#f87171}}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:1180px;margin:0 auto;padding:24px}h1{font-size:20px;margin:0 0 4px}.mute{color:var(--mute)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.tile b{display:block;font-size:22px}
.bar-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0}
input,button{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
input{flex:1;min-width:200px}button{cursor:pointer}button.on{border-color:var(--bar);color:var(--bar)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{cursor:pointer;user-select:none;font-weight:600;white-space:nowrap}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
tr.topic{cursor:pointer}tr.topic:hover{background:color-mix(in srgb,var(--bar) 6%,transparent)}
.score{display:flex;align-items:center;gap:8px;justify-content:flex-end}.score i{display:block;height:6px;border-radius:3px;background:var(--bar)}
.trend{font-weight:600}.rising{color:var(--up)}.steady{color:var(--flat)}.fading{color:var(--down)}
.detail td{background:var(--bg)}.detail table{border:none}.detail th{cursor:default}
a{color:var(--bar)}.src{font-size:12px;color:var(--mute)}
</style></head><body><main>
<h1>tabtrail</h1><div class="mute" id="sub"></div>
<div class="tiles" id="tiles"></div>
<div class="bar-row"><input id="q" placeholder="Filter topics by words or examples">
<span id="trends"></span><span id="sources"></span></div>
<table><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table>
<p class="mute">Score = attention hours, halved every 7 days. Trend ratio = 7-day average ÷ 60-day average: 1.25 or more is rising, 0.8 or less is fading. Click a topic to see its top items.</p>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("data").textContent), T = D.topics;
const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
const st = {q: "", trend: "all", source: "all", key: "score", dir: -1, open: new Set()};
const maxScore = Math.max(...T.map(t => t.score), 1e-9);
document.getElementById("sub").textContent = "Last run " + (D.last_run || "unknown") + " · page made " + D.made;
const tiles = [["Topics", T.length], ["Rising", T.filter(t => t.trend === "rising").length], ["Fading", T.filter(t => t.trend === "fading").length],
  ["Visits", D.status.brave_visits], ["Chat messages", D.status.chat_messages]];
document.getElementById("tiles").append(...tiles.map(([k, v]) => el("div", {className: "tile"}, el("b", {textContent: v.toLocaleString()}), el("span", {className: "mute", textContent: k}))));
const chips = (id, field, values) => document.getElementById(id).append(...values.map(v => {
  const b = el("button", {textContent: v}); b.onclick = () => { st[field] = v; draw(); }; b.dataset.f = field; b.dataset.v = v; return b; }));
chips("trends", "trend", ["all", "rising", "steady", "fading"]); chips("sources", "source", ["all", "brave", "claude", "pi"]);
const cols = [["rank", "#", 1], ["words", "Topic (top words)"], ["score", "Score", 1], ["trend_ratio", "Trend ratio", 1], ["trend", "Trend"],
  ["attention_h", "Hours (all time)", 1], ["events", "Events", 1], ["items", "Items", 1], ["sources", "Sources"]];
document.getElementById("head").append(...cols.map(([k, label, n]) => {
  const th = el("th", {textContent: label, className: n ? "n" : ""}); th.onclick = () => { st.dir = st.key === k ? -st.dir : (n ? -1 : 1); st.key = k; draw(); }; return th; }));
document.getElementById("q").oninput = e => { st.q = e.target.value.toLowerCase(); draw(); };
function detail(t) {
  const rows = t.top_items.map(i => el("tr", {}, el("td", {}, i.text, el("div", {className: "src"}, i.example_location || "")),
    el("td", {className: "n", textContent: i.attention_min}), el("td", {className: "n", textContent: i.events}),
    el("td", {textContent: i.last_seen, style: "white-space:nowrap"}), el("td", {textContent: i.sources})));
  const head = el("tr", {}, ...["Item", "Minutes", "Events", "Last seen", "Sources"].map((h, j) => el("th", {textContent: h, className: j && j < 3 ? "n" : ""})));
  return el("tr", {className: "detail"}, el("td", {colSpan: cols.length}, el("table", {}, el("thead", {}, head), el("tbody", {}, ...rows))));
}
function draw() {
  document.querySelectorAll("button[data-f]").forEach(b => b.classList.toggle("on", st[b.dataset.f] === b.dataset.v));
  const rows = T.filter(t => (st.trend === "all" || t.trend === st.trend) && (st.source === "all" || t.sources.split(",").includes(st.source))
      && (!st.q || (t.words + " " + t.examples).toLowerCase().includes(st.q)))
    .sort((a, b) => (a[st.key] > b[st.key] ? 1 : a[st.key] < b[st.key] ? -1 : 0) * st.dir);
  const body = document.getElementById("body"); body.replaceChildren();
  for (const t of rows) {
    const tr = el("tr", {className: "topic"}, el("td", {className: "n", textContent: t.rank}), el("td", {textContent: t.words || "(no words)"}),
      el("td", {className: "n"}, el("div", {className: "score"}, el("i", {style: "width:" + Math.max(2, 80 * t.score / maxScore) + "px"}), String(t.score))),
      el("td", {className: "n", textContent: t.trend_ratio}), el("td", {className: "trend " + t.trend, textContent: t.trend}),
      el("td", {className: "n", textContent: t.attention_h}), el("td", {className: "n", textContent: t.events}),
      el("td", {className: "n", textContent: t.items}), el("td", {textContent: t.sources}));
    tr.onclick = () => { st.open.has(t.topic_id) ? st.open.delete(t.topic_id) : st.open.add(t.topic_id); draw(); };
    body.append(tr); if (st.open.has(t.topic_id)) body.append(detail(t));
  }
  if (!rows.length) body.append(el("tr", {}, el("td", {colSpan: cols.length, className: "mute", textContent: "No topic matches."})));
}
draw();
</script></body></html>
"""
