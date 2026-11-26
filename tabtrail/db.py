"""One DuckDB file holds raw rows, caches and results. Raw tables only grow, so history survives the browser's 90-day limit."""
import duckdb
SCHEMA = """
CREATE TABLE IF NOT EXISTS brave_visits(visit_id BIGINT PRIMARY KEY, ts BIGINT, url VARCHAR, host VARCHAR, title VARCHAR,
  how VARCHAR, open_s DOUBLE, focus_s DOUBLE, search_term VARCHAR);
CREATE TABLE IF NOT EXISTS chat_messages(msg_id VARCHAR PRIMARY KEY, source VARCHAR, session_id VARCHAR, ts BIGINT,
  cwd VARCHAR, text VARCHAR, location VARCHAR);
CREATE TABLE IF NOT EXISTS lines(text_in VARCHAR, model VARCHAR, line VARCHAR, PRIMARY KEY(text_in, model));
CREATE TABLE IF NOT EXISTS embeddings(text VARCHAR, model VARCHAR, vec FLOAT[], PRIMARY KEY(text, model));
CREATE SEQUENCE IF NOT EXISTS run_seq;
CREATE TABLE IF NOT EXISTS runs(run_id BIGINT PRIMARY KEY, ts BIGINT, stats JSON);
CREATE TABLE IF NOT EXISTS topics(run_id BIGINT, topic_id INT, words VARCHAR, items INT, events INT, attention_h DOUBLE,
  trend_ratio DOUBLE, score DOUBLE, sources VARCHAR, examples VARCHAR, PRIMARY KEY(run_id, topic_id));
CREATE TABLE IF NOT EXISTS topic_items(run_id BIGINT, text VARCHAR, topic_id INT);
CREATE TABLE IF NOT EXISTS topic_centroids(run_id BIGINT, topic_id INT, vec FLOAT[], sim_p10 DOUBLE, sim_median DOUBLE, PRIMARY KEY(run_id, topic_id));
"""
def connect(cfg, read_only=False):
    con = duckdb.connect(str(cfg.db), read_only=read_only)
    if not read_only:
        # topics holds only the latest run: rebuild a table from before the trend_ratio column
        if con.execute("select 1 from information_schema.columns where table_name='topics' and column_name='recent_share'").fetchall():
            con.execute("DROP TABLE topics")
        con.execute(SCHEMA)
    return con
