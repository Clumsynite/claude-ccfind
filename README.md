# ccfind

[![CI](https://github.com/Clumsynite/claude-ccfind/actions/workflows/ci.yml/badge.svg)](https://github.com/Clumsynite/claude-ccfind/actions/workflows/ci.yml)
[![Release workflow](https://github.com/Clumsynite/claude-ccfind/actions/workflows/release.yml/badge.svg)](https://github.com/Clumsynite/claude-ccfind/actions/workflows/release.yml)
[![Release](https://img.shields.io/badge/release-v0.1.1-blue)](https://github.com/Clumsynite/claude-ccfind/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Find any past Claude Code session by what was said in it, across every project, then resume it. Also
shows a **word bank and usage stats**:
- the words and openers you use most
- recurring prompt templates
- prompt and conversation length
- code lines Claude wrote
- tokens by model, project and week

Everything runs locally: a SQLite FTS5 index over your transcripts in `~/.claude/projects`. No model is
called, and nothing leaves your machine. It's a single Python 3 file with no dependencies.

## Install

```sh
ln -sf "$PWD/scripts/ccfind" ~/.local/bin/ccfind    # any directory on your PATH
ccfind index --stats                                 # first build: ~10–20 s for ~1.5 GB of transcripts
```

Every command after that updates the index incrementally before it runs. When nothing has changed, that
takes a few milliseconds.

## Search

```sh
ccfind stripe webhook             # sessions containing all the words, best match first;
                                   # each result ends with a copy-paste `cd … && claude --resume …` line
ccfind -p api --since 14d deploy   # filter by project substring and date (7d, 12h, 2026-09-01)
ccfind -b main login bug           # filter by git branch
ccfind --any foo bar               # any word instead of all
ccfind --raw 'deploy NEAR/5 fail'  # FTS5 query syntax
ccfind --json …                    # machine-readable output
ccfind open 1                      # print `cd <dir> && claude --resume <id>` for result #1
ccfind open 1 -x                   # …and run it (refused inside a Claude Code session)
ccfind show 3f2a91 -g webhook      # condensed transcript, optionally only the matching messages
```

- **What is searched:**
  - your prompts, including ones queued while Claude was busy
  - Claude's replies
  - subagent replies
  - slash-command arguments
  - session titles, project paths and branches
- **Not searched by default:** tool calls and outputs. `ccfind index --mode deep` adds them (capped at 2 KB
  each), which makes the index about 4x bigger. `--mode text` switches back.
- **Filters:** `--no-agents`, `--exclude-current` and `--include-tmp` (see Defaults).
- **Typos:** a word that appears in 5 or fewer messages, but is one or two edits (including a swapped pair
  of letters) from a common word, also matches the common word. So `ccfind price comapre` finds
  "price compare" sessions, and a line like `(comapre looks like a typo; also matching compar)` tells you.
  A hyphenated or dotted term that matches nothing as a phrase is searched as separate words.
  `--exact` turns both off.

## Defaults

Search and stats hide headless sessions (`claude -p` / SDK runs, recorded as `entrypoint: sdk-cli`)
and sessions whose working directory is under `/tmp`. These are usually test runs or scratch sessions
that repeat your query word for word. Add `--include-tmp` to bring them back.

`agent` is a subcommand, so to search for the word "agent" write `ccfind search agent`.

## Stats

```sh
ccfind stats                    # terminal report
ccfind stats -p api --since 30d # one project, last 30 days
ccfind stats --json             # all sections as JSON
ccfind stats --html report.html # self-contained HTML with charts (no network requests)
```

The report has these sections:
- Overview and projects
- Activity: per week, and a weekday × hour grid
- Your prompts: length and the longest ones
- Word bank for you and for Claude, each with:
  - top words (with how many sessions they appear in)
  - word pairs
  - openers
  - recurring templates (5-word phrases reused in 3+ sessions)
  - slash commands
- Conversations: length, duration and the longest ones
- Tools used
- Code lines Claude wrote through Edit/Write/MultiEdit/NotebookEdit. Rejected or failed edits are
  excluded, and subagent edits are included.
- Tokens: input, output, cache write and cache read, by model, project and week

Pasted blocks, code, URLs, file paths, image placeholders and lines that look like terminal output are
stripped before words are counted. Each word counts once per message.

Prompts with more than 6 non-empty lines are almost always pasted output (logs, tool results). They are
left out of *your* word bank, which covers words, pairs, openers and templates, but they still count
everywhere else. The report says how many were left out (`paste_like_excluded` in `--json`). Change the
limit with `--max-prompt-lines N`, or turn it off with `0`.

**Cost** appears only if you create `~/.config/ccfind/prices.json` with $ per million tokens for each
model, copied from https://www.anthropic.com/pricing:

```json
{ "claude-opus-5": { "input": 0, "output": 0, "cache_write": 0, "cache_read": 0 } }
```

## Claude Code plugin

The repo is also a plugin with two skills that call the script. The search itself uses no model.
- `/ccfind:find-session <words>` ranks sessions and gives the resume command.
- `/ccfind:session-stats` summarises your stats.

```sh
claude --plugin-dir /path/to/ccfind
```

### Install from the private marketplace

The GitHub repo is private. Claude Code clones it with your own git credentials, and it never prompts.
With SSH access to the repo:

```
/plugin marketplace add git@github.com:Clumsynite/claude-ccfind.git
/plugin install ccfind@clumsyknight-ccfind
```

If you use an SSH host alias for this GitHub account, put it in place of `github.com`. For HTTPS, run
`gh auth login` and `gh auth setup-git` first, then add `https://github.com/Clumsynite/claude-ccfind.git`.

## Keep the index warm (macOS)

```sh
ccfind agent install              # launchd job: runs `ccfind index` every 10 min, low priority
ccfind agent install --interval 1800
ccfind agent status               # installed / loaded / last exit / last index / log tail
ccfind agent uninstall
```

The job runs quietly and never waits. If another ccfind is already indexing, it skips that run. Errors go
to `~/.cache/ccfind/agent.log`, which is rotated to `agent.log.1` past 1 MB. It runs
`/opt/homebrew/bin/python3` when that exists. If the Python or the script moves, `agent status` warns you
to run `agent install` again.

Only one ccfind indexes at a time; a file lock next to the database enforces that. An older ccfind never
downgrades an index built by a newer one: it exits with code 5 and tells you so.

## Privacy

The index holds the text of your conversations. It lives at `~/.cache/ccfind/index.db` (override it with
`CCFIND_DB`), in a 0700 directory with 0600 files. The HTML report is also written 0600. Transcripts
are only ever read, never modified. Delete `~/.cache/ccfind` at any time; `ccfind index` rebuilds it.

If a transcript is deleted (Claude Code removes old ones after `cleanupPeriodDays`, 30 by default), its
rows are dropped from the index on the next run.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The tests use synthetic transcripts only.
