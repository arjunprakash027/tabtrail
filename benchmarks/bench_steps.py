"""Time every pipeline step with pytest-benchmark.

Run:      uv run pytest benchmarks/bench_steps.py --benchmark-autosave
Compare:  uv run pytest-benchmark compare --group-by=name

The benchmark works on a copy of data/ (no model weights) with TABTRAIL_LINES=truncate,
so it never changes the real store and never calls the local LLM. Embeddings come from the cache.
Ollama must run only if a text has no cached embedding.
Set BENCH_ROUNDS to change how often each step runs (default 3).
"""
import os, shutil, subprocess, sys
import pytest
from tabtrail import config

ROUNDS = int(os.environ.get("BENCH_ROUNDS", "3"))
STEPS = ["ingest", "events", "normalized", "items", "embeddings", "clusters", "topics", "profile_md"]

@pytest.fixture(scope="session")
def env(tmp_path_factory):
    home = tmp_path_factory.mktemp("tabtrail-bench")
    shutil.copytree(config.DEFAULT_HOME, home, dirs_exist_ok=True, ignore=shutil.ignore_patterns("models", "*.wal"))
    os.environ.update(TABTRAIL_HOME=str(home), TABTRAIL_LINES="truncate")
    from tabtrail import db, pipeline
    cfg = config.load(); con = db.connect(cfg)
    from hamilton import driver
    res = driver.Builder().with_modules(pipeline).build().execute(STEPS, inputs={"cfg": cfg, "con": con})
    yield {"cfg": cfg, "con": con, **res}   # every step's output, so each step can run alone
    con.close()

def _bench(benchmark, env, step):
    from tabtrail import pipeline
    fn = getattr(pipeline, step)
    args = {name: env[name] for name in fn.__code__.co_varnames[:fn.__code__.co_argcount]}
    benchmark.group = "steps"
    benchmark.pedantic(fn, kwargs=args, rounds=ROUNDS, iterations=1, warmup_rounds=0)

@pytest.mark.parametrize("source", ["brave", "claude", "pi"])
def test_ingest_source(benchmark, env, source):
    """ingest, one source at a time: the part a Rust port targets."""
    from tabtrail import adapters
    benchmark.group = "ingest"
    benchmark.pedantic(adapters.ALL[source], args=(env["cfg"], env["con"]), rounds=ROUNDS, iterations=1)

@pytest.mark.parametrize("step", STEPS)
def test_step(benchmark, env, step):
    _bench(benchmark, env, step)

def test_full_run(benchmark, tmp_path_factory):
    """tabtrail run in a new process: what a person waits for, including imports and numba compile.
    It uses its own copy, because DuckDB allows one writer and the step fixture holds the other copy open."""
    home = tmp_path_factory.mktemp("tabtrail-full")
    shutil.copytree(config.DEFAULT_HOME, home, dirs_exist_ok=True, ignore=shutil.ignore_patterns("models", "*.wal"))
    env = {**os.environ, "TABTRAIL_HOME": str(home), "TABTRAIL_LINES": "truncate"}
    def run():
        r = subprocess.run([sys.executable, "-m", "tabtrail.cli", "run"], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]
    benchmark.group = "full"
    benchmark.pedantic(run, rounds=max(1, ROUNDS // 3), iterations=1)
