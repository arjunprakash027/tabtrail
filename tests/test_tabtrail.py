"""Simple checks for the filters, the brave adapter and the topic writes."""
import sqlite3
from types import SimpleNamespace
import duckdb, numpy as np, pandas as pd, pytest
from tabtrail import adapters, db, pipeline, query

def test_secrets_are_redacted():
    assert adapters._redact("my key is sk-abcdefghijklmnop1234 ok") == "my key is [secret] ok"
    assert adapters._redact("ghp_" + "a" * 24) == ""          # only a secret: drop the message
    assert adapters._redact("how do I sort a list in python") == "how do I sort a list in python"

@pytest.mark.parametrize("text", ["Task: review the diff", "You are a code reviewer", "Plannotator Inbox: new card"])
def test_agent_written_messages_are_dropped(text):
    assert adapters.AGENT_WRITTEN.search(text)

@pytest.mark.parametrize("text, is_ack", [("continue", True), ("try again please", True),
                                          ("google cloud run pricing", False), ("now fix the parser bug", False)])
def test_replies_are_not_interests(text, is_ack):
    assert bool(pipeline.ACK.match(text)) == is_ack

def test_page_titles_are_cleaned():
    assert pipeline._clean_title("(3) Rust ownership explained - YouTube") == "Rust ownership explained"
    assert pipeline.BRAND_ONLY.match("LinkedIn")

def test_long_chat_gets_cached_line_or_first_words():
    long_text = " ".join(f"w{i}" for i in range(40))
    e = pd.DataFrame({"kind": ["chat", "chat", "page"], "text": [long_text, long_text + " x", long_text]})
    out = pipeline._with_lines(e, {long_text: "cached line"})
    assert list(out.line) == ["cached line", pipeline._first_words(long_text), long_text]

@pytest.mark.parametrize("share, trend", [(0.5, "rising"), (0.49, "steady"), (0.15, "steady"), (0.14, "fading")])
def test_trend_is_the_same_in_python_and_sql(share, trend):
    assert pipeline._trend(share) == trend
    assert duckdb.sql(f"select {query.TREND} from (select {share} as recent_share)").fetchall()[0][0] == trend

def test_brave_redacts_and_deletes_its_copy(tmp_path):
    prof = tmp_path / "profile"; prof.mkdir()
    h = sqlite3.connect(prof / "History")
    h.executescript("""create table urls(id integer primary key, url text, title text);
        create table visits(id integer primary key, url int, visit_time int, transition int, visit_duration int);
        create table keyword_search_terms(url_id int, term text);""")
    h.execute("insert into urls values (1, ?, 'Welcome')", ["https://x.com/login?t=eyJ" + "a" * 30 + ".bbb"])
    h.execute("insert into visits values (1, 1, 13300000000000000, 0, 20000000)"); h.commit(); h.close()
    cfg = SimpleNamespace(profile=prof, raw=tmp_path / "raw", db=tmp_path / "t.duckdb")
    con = db.connect(cfg)
    assert adapters.brave(cfg, con)["new"] == 1
    url = con.execute("select url from brave_visits").fetchall()[0][0]
    assert "eyJ" not in url and "[secret]" in url
    assert list(cfg.raw.iterdir()) == []

def _items(texts):
    n = len(texts)
    return pd.DataFrame({"text": texts, "attention_s": [60.0] * n, "recent_s": [0.0] * n, "events": [1] * n, "sources": ["brave"] * n})

def test_no_topics_writes_nothing(tmp_path):
    cfg = SimpleNamespace(db=tmp_path / "t.duckdb", profile_md=tmp_path / "profile.md")
    con = db.connect(cfg)
    items, emb = _items(["a b c"] * 3), np.eye(3, dtype=np.float32)
    cl = pipeline.clusters(emb)
    assert (cl == -1).all()
    t = pipeline.topics(items, cl, emb, con)
    assert t.empty and con.execute("select count(*) from topics").fetchall()[0][0] == 0
    pipeline.profile_md(t, items, cl, cfg)
    assert not cfg.profile_md.exists()

def test_only_the_latest_run_is_kept(tmp_path):
    con = db.connect(SimpleNamespace(db=tmp_path / "t.duckdb"))
    items = _items(["rust ownership borrow", "rust borrow checker", "duckdb sql window", "duckdb sql join"])
    emb = np.array([[1, 0], [1, 0.1], [0, 1], [0.1, 1]], dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    cl = np.array([0, 0, 1, 1])
    for _ in range(2): last = pipeline.topics(items, cl, emb, con).attrs["run_id"]
    for tab in pipeline.RUN_TABLES:
        assert con.execute(f"select distinct run_id from {tab}").fetchall() == [(last,)]
