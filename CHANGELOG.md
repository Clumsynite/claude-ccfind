# Changelog

All notable changes to ccfind are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

To release: add a section for the new version at the top, bump `version` in `.claude-plugin/plugin.json`,
then push to `main`. CI refuses a version without a section here,
and the Release workflow tags `ccfind--v<version>`.

## [Unreleased]

### Changed
- The repository is now public. The README shows the live release badge (the static badge and its CI
  check are gone), plus Claude Code, Python, dependency and platform badges. Install with
  `/plugin marketplace add Clumsynite/claude-ccfind`.

## [0.1.1] - 2026-09-25

### Added
- **Typo tolerance in search.** A word that appears in 5 or fewer messages, but is within one or two edits
  of a common word (a swapped pair of letters counts as one edit), also matches the common word. So
  `ccfind price comapre` finds "price compare" sessions. A note names each correction.
- `--exact` turns typo tolerance off.
- Every search result ends with a ready-to-paste resume command (`cd <dir> && claude --resume <id>`),
  which replaces the bare `id:` line. `--json` results carry it as `resume`.
- A hyphenated or dotted term that matches nothing as a phrase (e.g. `price-comapre`) is searched as
  separate words.

## [0.1.0] - 2026-09-25

The first release.

### Added
- **Search.** A local SQLite FTS5 index over Claude Code transcripts in `~/.claude/projects`. It covers
  your prompts (including prompts queued while Claude was busy), Claude's replies, subagent replies,
  slash-command arguments, titles, project paths and branches. Results are ranked per session, with
  snippets.
- `ccfind open <n>` prints the resume command (`-x` runs it). `ccfind show` prints a condensed
  transcript.
- **Incremental indexing** that reads only new bytes and handles live, truncated, replaced and deleted
  files. It updates before every command.
- `ccfind index --mode deep` also indexes tool calls and tool output.
- **Filters** by project, branch, date, and with `--any`, `--raw`, `--json`, `--no-agents`,
  `--exclude-current`.
- **Hidden by default:** headless (`claude -p` / SDK) sessions and `/tmp` sessions. `--include-tmp` brings
  them back.
- **`ccfind stats`, a word bank and usage stats**, as terminal output, `--json` or a self-contained
  `--html` report:
  - words, word pairs and openers
  - recurring prompt templates
  - slash commands
  - prompt and conversation length
  - tools used
  - code lines Claude wrote (rejected edits excluded)
  - tokens by model, project and week
  - optional cost from `~/.config/ccfind/prices.json`
- Pasted prompts (more than 6 non-empty lines) are left out of your word bank; change the limit with
  `--max-prompt-lines`.
- **`ccfind agent install|status|uninstall`**, a macOS launchd job that keeps the index warm every
  10 minutes.
- **Safety:**
  - A file lock allows one indexer at a time.
  - An older ccfind never downgrades a newer index; it exits with code 5.
  - The index and report files are private (0600).
- **Claude Code plugin skills:** `/ccfind:find-session` and `/ccfind:session-stats`.

[Unreleased]: https://github.com/Clumsynite/claude-ccfind/compare/ccfind--v0.1.1...HEAD
[0.1.1]: https://github.com/Clumsynite/claude-ccfind/compare/ccfind--v0.1.0...ccfind--v0.1.1
[0.1.0]: https://github.com/Clumsynite/claude-ccfind/releases/tag/ccfind--v0.1.0
