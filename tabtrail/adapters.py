"""One adapter per source. Each reads its own format and adds new raw rows. Running one twice adds nothing."""
import json, re, shutil, sqlite3, datetime as dt, hashlib
import pandas as pd

EPOCH = 11644473600  # seconds from 1601-01-01 (Chromium time) to 1970-01-01

def brave(cfg, con):
    src = cfg.profile / "History"
    if not src.exists():
        raise SystemExit(f"No History file at {src}. Set TABTRAIL_PROFILE, or give your terminal Full Disk Access (macOS).")
    cfg.raw.mkdir(exist_ok=True)
    snap = cfg.raw / "History.sqlite"
    shutil.copyfile(src, snap)  # the browser locks the live file, so read a copy, then delete it
    try:
        b = sqlite3.connect(snap)
        ctx = b.execute("select 1 from sqlite_master where name='context_annotations'").fetchone()
        df = pd.read_sql_query(f"""
        select v.id visit_id, v.visit_time/1000000-{EPOCH} ts, u.url, u.title,
          case v.transition & 255 when 0 then 'link' when 1 then 'typed' when 2 then 'bookmark' when 5 then 'search'
            when 7 then 'form' when 8 then 'reload' else 'other' end how,
          v.visit_duration/1e6 open_s, {'c.total_foreground_duration/1e6' if ctx else 'NULL'} focus_s, k.term search_term
        from visits v join urls u on u.id = v.url
        {'left join context_annotations c on c.visit_id = v.id' if ctx else ''}
        left join (select url_id, min(term) term from keyword_search_terms group by url_id) k on k.url_id = u.id""", b)
        b.close()
    finally:
        snap.unlink(missing_ok=True)
    for col in ("url", "title", "search_term"):   # tokens in login links and pasted keys never go in the store
        df[col] = df[col].map(lambda s: SECRET.sub("[secret]", s) if isinstance(s, str) else s)
    df["host"] = df["url"].str.extract(r"^[a-z]+://([^/]+)", expand=False).fillna("")
    before = con.execute("select count(*) from brave_visits").fetchall()[0][0]
    con.register("new_rows", df)
    con.execute("INSERT OR IGNORE INTO brave_visits SELECT visit_id, ts, url, host, title, how, open_s, focus_s, search_term FROM new_rows")
    con.unregister("new_rows")
    after = con.execute("select count(*) from brave_visits").fetchall()[0][0]
    return {"source": "brave", "new": after - before, "total": after}

SKIP_START = ("<", "[Request interrupted", "Caveat:", "/")
def _text(content):
    if isinstance(content, str): return content
    if isinstance(content, list):
        return " ".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""

def _insert_chats(con, rows, source):
    before = con.execute("select count(*) from chat_messages where source=?", [source]).fetchall()[0][0]
    if rows:
        df = pd.DataFrame(rows, columns=["msg_id", "source", "session_id", "ts", "cwd", "text", "location"])
        con.register("new_rows", df)
        con.execute("INSERT OR IGNORE INTO chat_messages SELECT * FROM new_rows")
        con.unregister("new_rows")
    after = con.execute("select count(*) from chat_messages where source=?", [source]).fetchall()[0][0]
    return {"source": source, "new": after - before, "total": after}

def _ts(s):
    try: return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception: return None

def claude(cfg, con):
    """Claude Code keeps one JSONL file per session. Keep only what the person typed."""
    rows = []
    for f in cfg.claude_dir.glob("*/*.jsonl"):   # top level only: subagent files sit deeper
        for i, line in enumerate(f.open(errors="ignore"), 1):
            try: r = json.loads(line)
            except ValueError: continue
            if r.get("type") != "user" or r.get("isMeta") or r.get("isSidechain"): continue
            t = _redact(_text(r.get("message", {}).get("content")).strip())
            if not t or t.startswith(SKIP_START) or AGENT_WRITTEN.search(t): continue
            rows.append((r.get("uuid") or f"{f.stem}:{i}", "claude", f.stem, _ts(r.get("timestamp", "")), r.get("cwd", ""), t, f"{f}#L{i}"))
    return _insert_chats(con, rows, "claude")

SKILL_BLOCK = re.compile(r"<skill\b.*?</skill>", re.S)
AGENT_WRITTEN = re.compile(r"^(Task:|Execute |Review-only task|Review one of my past|Independently review|Read [\w./-]+\.md|Read the brief|You prepare |You help |Now use our |I'm checking whether |Live smoke finding|You are |# )"
                           r"|This parent session is the sole writer|^The [\w-]+ plugin sent a message|^Plannotator Inbox:|^This session is being continued from a previous conversation")
# keys and tokens never go in the store
SECRET = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|[A-Za-z]{2,4}_(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Z])[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+)\b")
def _redact(t):
    t = SECRET.sub("[secret]", t)
    return "" if re.fullmatch(r"(\[secret\]\s*)+", t) else t
def pi(cfg, con):
    """Pi keeps one JSONL file per session. Drop sessions and messages that other agents started."""
    rows = []
    for f in cfg.pi_dir.rglob("*.jsonl"):
        lines = f.open(errors="ignore").readlines()
        try: head = json.loads(lines[0])
        except (ValueError, IndexError): continue
        if head.get("type") != "session": continue                       # subagent record files
        if str(head.get("cwd", "")).startswith(("/private/tmp", "/tmp")): continue  # throwaway agent workers
        for i, line in enumerate(lines[1:], 2):
            try: r = json.loads(line)
            except ValueError: continue
            m = r.get("message") or {}
            if m.get("role") != "user": continue
            t = _redact(SKILL_BLOCK.sub("", _text(m.get("content"))).strip())   # keep what was typed after a skill block
            if not t or t.startswith(SKIP_START) or AGENT_WRITTEN.search(t): continue
            mid = r.get("id") or hashlib.sha1(f"{f}:{i}".encode()).hexdigest()[:16]
            rows.append((f"pi:{mid}", "pi", head.get("id", f.stem), _ts(r.get("timestamp", "") or ""), head.get("cwd", ""), t, f"{f}#L{i}"))
    return _insert_chats(con, rows, "pi")

ALL = {"brave": brave, "claude": claude, "pi": pi}
