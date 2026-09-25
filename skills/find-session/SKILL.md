---
name: find-session
description: Find a past Claude Code session by what was discussed in it, across all projects, and give the command to resume it. Use when the user asks which session, where or when they worked on something, or to find, locate or resume an earlier conversation.
argument-hint: "<words from the conversation> [-p project] [--since 7d]"
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ccfind" *)
---

# Find session

The search is done by the `ccfind` script: a local SQLite full-text index over the transcripts in
`~/.claude/projects`. Don't search any other way. Don't grep or read transcript files, and don't
guess from memory.

## Steps

1. Take the user's words exactly as given: `$ARGUMENTS`. If it's empty, ask what the session was about and stop.
2. Run one Bash command. Pass each word as a separate single-quoted argument after `--`. Put the
   options `-p <project>`, `--since <7d|YYYY-MM-DD>` and `-b <branch>` before `--`, and only when
   the user gave them:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ccfind" search --json -n 8 --exclude-current -- 'word1' 'word2'
   ```

   `--exclude-current` leaves out this session, which would otherwise always match itself because it
   contains the query you just ran.

3. If the result is `[]`, say nothing matched all the words. Then run the same command once more with
   `--any` added before `--`, and label the new results as partial matches.
4. Show a compact table with these columns: `#`, date (from `ended`), project, title, and the snippet
   (brackets mark the matching words). Show the full session `id` under each row.
5. Finish with the top result's `resume` field in its own code block, so it can be copied as is. Mention that `ccfind open <n>` prints the command for any row.
   Don't run `claude` yourself.
