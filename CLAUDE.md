# tabtrail

tabtrail turns local browser history and AI chat logs into a map of interests. All data stays on this machine.

## Layout

| Path | Contents |
|---|---|
| `tabtrail/pipeline.py` | The pipeline. One public function is one Hamilton step. |
| `tabtrail/adapters.py` | One adapter per source: `brave`, `claude`, `pi`. |
| `tabtrail/query.py` | Read-only questions: `interests`, `topic`, `match`, `last_run`. |
| `tabtrail/cli.py` | The `tabtrail` command. |
| `tabtrail/dashboard.py` | `tabtrail dashboard`: one static HTML page of the latest run, in the data folder. |
| `tabtrail/db.py` | DuckDB schema. |
| `tabtrail/config.py` | Settings from `TABTRAIL_*` environment variables. |
| `tests/` | Pytest checks. Run `uv run pytest`. |
| `docs/scores.md` | How each score is calculated. Update it when a formula changes. |
| `experiments/` | Old one-off scripts. Local only, not in git. Do not import from them. |
| `examples/` | `demo_history.py` makes a fake History file for demos. |
| `docs/design/` | Local design notes. Not in git. |

## Pipeline steps

`ingest` → `events` → `normalized` → `items` → `embeddings` → `clusters` → `topics` → `profile_md`

## Rules for code in pipeline.py

1. Hamilton makes a step from every public function in `pipeline.py`. Give helper functions a name that starts with `_`.
2. Give every parameter and every return value a type hint. Hamilton fails without them.
3. The name of a parameter is the name of the step it needs. Do not rename a step without a change to every step that uses it.
4. Keep raw tables append-only. `brave_visits` and `chat_messages` must keep rows after the browser deletes them.
5. Cache expensive work in DuckDB: `embeddings` and `lines`. Never call a model again for a text that is in the cache.

## DuckDB

- DuckDB allows one writer. A read fails while `tabtrail run` writes. `query.py` reports this as "The pipeline is running."
- Read a full result before the next query on the same connection. Use `.fetchall()`, not `.fetchone()`. DuckDB 2 rejects a new query on a connection with an unread result.

## Privacy rules

1. Do not send raw history or chat text to a remote service.
2. Replace keys and tokens with `[secret]` before a row goes into the store. The pattern is `adapters.SECRET`.
3. Drop messages that agents or plugins wrote. The pattern is `adapters.AGENT_WRITTEN`. Add a pattern when a new agent-written message gets through.
4. Do not commit the data folder. `data/` is in `.gitignore`.

## Run and test

Everything tabtrail stores is in `data/` in this repo: the database, `profile.md` and the MLX model weights (`data/models`). `config.DEFAULT_HOME` points there when tabtrail runs from this checkout. The installed `tabtrail` command is an editable install, so it uses the same folder. `data/` is in `.gitignore`. Never commit it. For a risky change, copy it to a test folder first:

```sh
cp -R ~/.local/share/tabtrail /tmp/tabtrail-test && export TABTRAIL_HOME=/tmp/tabtrail-test
uv run tabtrail run                 # whole pipeline, about 40 s with a warm cache
uv run tabtrail run --to events     # stop after one step
TABTRAIL_LINES=truncate uv run tabtrail run   # skip the local LLM
```

After a change to clustering or filters, check the result:

1. Run `tabtrail interests --mode top` and `--mode rising`. The top topics must be real subjects, not replies or page types.
2. Run `tabtrail match` with one search, one page title and one chat text.

## For an AI agent that uses tabtrail

1. Run `tabtrail --json last-run`. If `should_run` is true, run `tabtrail run`.
2. Ask with `tabtrail --json interests --mode top|recent|rising|fading`. Add `--source brave|claude|pi` to filter.
3. Look inside a topic with `tabtrail --json topic <topic_id>`.
4. Place new text with `tabtrail --json match --kind search|page|chat --text "..."`. The text is not saved.

## Models

- Embeddings: `nomic-embed-text` in Ollama.
- One-line summaries of long chat messages: `mlx-community/Qwen3-1.7B-4bit` in MLX. About 1 to 2 s for each message on an 8 GB M1. The 4B model was 2 to 3 times slower for a small gain in quality.
