---
name: tabtrail
description: Read the user's interests from their local browser history and AI chat logs with the tabtrail CLI. Use when you need to know what the user cares about now, which topics are rising or fading, or whether a new text matches an interest.
---

# tabtrail for AI agents

tabtrail is a local command-line tool. It reads browser history (Brave, Chrome, Edge, Arc) and chat logs (Claude Code, Pi). It groups them into topics. It gives each topic a score and a trend.

Repository: https://github.com/arjunprakash027/tabtrail

## Privacy rules

1. The output contains private data: page titles, URLs, chat text and file paths.
2. Use the output only for the task that the user gave you.
3. Do not send the output to a remote service, a public page or another person unless the user tells you to.
4. If you run on a cloud model, the output goes to your model provider. Tell the user this before your first call, unless the user already approved it.

## Check that tabtrail is ready

1. Run `tabtrail --help`. If the command is not found, tell the user to install it (see "Install").
2. Run `tabtrail --json last-run`.
3. If `should_run` is `true`, run `tabtrail run`. A run takes about 40 s with a warm cache. The first run takes longer.

## Install

The user installs tabtrail. Do not install it without the user's approval.

```sh
git clone https://github.com/arjunprakash027/tabtrail.git && cd tabtrail
uv tool install --editable .      # add --with mlx-lm on Apple Silicon
ollama pull nomic-embed-text      # Ollama must run
tabtrail run
```

On macOS, the terminal needs Full Disk Access to read the browser History file.

## Commands

Put `--json` before the command. All commands except `interests` and `profile` print JSON without it.

| Task | Command |
|---|---|
| Find out if a new run is necessary | `tabtrail --json last-run` |
| Update the topics | `tabtrail run` |
| Get the top topics | `tabtrail --json interests --mode top --limit 10` |
| Get the topics that grow now | `tabtrail --json interests --mode rising` |
| Get the topics that the user stopped | `tabtrail --json interests --mode fading` |
| Get topics from one source | add `--source brave`, `--source claude` or `--source pi` |
| Look inside one topic | `tabtrail --json topic <topic_id>` |
| Place a new text | `tabtrail --json match --kind search\|page\|chat --text "..."` |
| Make a page for the user | `tabtrail dashboard` (prints the path of an HTML file) |
| Count the stored rows | `tabtrail --json status` |

`match` does not save the text.

## Fields

| Field | Meaning |
|---|---|
| `score` | Hours of attention. Each hour loses half its value every 7 days. A high score means much attention recently. |
| `trend_ratio` | Hours per day now (7-day half-life) ÷ usual hours per day (60-day half-life). 1 is the usual pace. |
| `trend` | `rising` if `trend_ratio` is 1.25 or more. `fading` if it is 0.8 or less. Else `steady`. |
| `attention_h` | All hours of attention, with no decay. |
| `events` | Number of visits, searches and chat messages. |
| `words` | The top words of the topic. It is a label, not a sentence. |
| `sources` | Sources of the topic: `brave`, `claude`, `pi`. |
| `rank` | Position by `score`. 1 is the highest. |
| `bucket` (match) | `existing`: the text joins `topic`. `new`: no topic is close enough. |
| `interest_score` (match) | The `score` of the joined topic. 0 for `new`. |
| `similarity`, `joins_if_at_least` (match) | The text joins a topic if `similarity` ≥ `joins_if_at_least`. |

## Rules for good results

1. A `topic_id` is valid only for the latest run. Get the IDs again after each `tabtrail run`.
2. Use `score` to find what matters now. Use `attention_h` for all-time interest.
3. Read `words` together with `examples` or `topic` output. The words alone can mislead.
4. For `match`, use `--kind page` for a page title, `--kind search` for a search query, and `--kind chat` for a message.
5. Many topics can be about one subject. Join them in your answer when their examples agree.

## Errors

| Output | Cause | Action |
|---|---|---|
| `{"error": "The pipeline is running. ..."}` | `tabtrail run` writes the database. | Wait until the run stops. Then try again. |
| `No topics yet. Run: tabtrail run` | No run made topics. | Run `tabtrail run`. |
| `No History file at ...` | The browser profile is not found, or the terminal has no disk access. | Tell the user. Do not change system settings. |
| Connection refused on port 11434 | Ollama does not run. | Tell the user to start Ollama. |

## Example

The user asks: "What am I into these days?"

1. `tabtrail --json last-run`. `should_run` is `true`, so run `tabtrail run`.
2. `tabtrail --json interests --mode rising --limit 5`.
3. For the first topic, `tabtrail --json topic <topic_id> --limit 5`.
4. Answer with the subjects, their trend and one or two examples each. Do not list URLs unless the user asks.
