---
name: session-stats
description: Show the user's Claude Code word bank and usage stats (the words and openers they use most, recurring prompt templates, prompt length, conversation length, code lines Claude wrote, and tokens), computed locally from their transcripts.
argument-hint: "[-p project] [--since 30d] [--html]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ccfind" *)
---

# Session stats

The stats come from the `ccfind` script's local index. Don't compute them any other way, and don't read transcript files.

## Steps

1. Build the options from `$ARGUMENTS`. Pass `-p <project>` and `--since <value>` through only when the
   user gave them.
2. Run:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ccfind" stats --top 10 [options]
   ```

3. Show the output. Lead with 3–5 observations the numbers support, such as the most common opener, the
   top recurring template (and whether it's worth turning into a skill), when they work most, and which
   project uses the most tokens. Don't invent numbers.
4. If the user asked for `--html`, or wants charts, run it again with `--html ~/ccfind-report.html` and
   tell them the path. The file stays local. Don't upload or publish it.
