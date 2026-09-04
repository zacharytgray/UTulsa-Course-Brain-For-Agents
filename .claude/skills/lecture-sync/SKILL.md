---
name: lecture-sync
description: >
  Pull new lecture transcripts from Granola class folders and file them under
  classes/<class>/lectures/. Use when the user says "sync lectures", "pull
  lectures", "file my lectures", or after a class day. Takes an optional class
  code to sync only that class.
---

# lecture-sync

File new Granola lecture recordings into the repo. Idempotent — safe to run any time, repeatedly. State lives entirely in the repo (the Granola MCP is read-only).

## Steps

1. Read every `classes/*/class.md` except `_template`. Collect `code`, `granola_folder_id`, and `starts` from frontmatter. If an argument was given, keep only that class.
   - A class with an empty `granola_folder_id`: call `list_meeting_folders` and look for a folder whose title contains the class code, exactly one candidate. If exactly one matches, write the id into `class.md` and continue. Zero or multiple matches: skip the class and list the candidates in the report — don't guess.
2. For each class, call `list_meetings` with its `granola_folder_id`. Default `time_range` is `last_30_days`; if the class has no filed lectures yet, use a custom range from the class's `starts` date so the first run catches everything.
3. Find what's already filed: grep `granola_id:` across that class's `lectures/*.md`. Skip any meeting whose id is already there. Never modify an existing lecture file. Lectures filed from another transcript source carry `source_id:` instead of `granola_id:` — leave those alone the same way.
4. For each new meeting, fetch notes with `get_meetings` and the full transcript with `get_meeting_transcript`, then write the file immediately — one meeting at a time, don't batch transcripts into context. If there are more than ~3 new meetings, delegate per class to subagents so transcripts never pile up in one context.
   - Empty or missing transcript (still processing right after class, or a plan issue): don't write a file for it. Report it as pending — the next run retries it.
5. Write `classes/<class>/lectures/YYYY-MM-DD.md` using the meeting's local date. If that file exists with a different `granola_id`, use `YYYY-MM-DD-2.md`, `-3`, etc.
6. Don't re-read the transcripts you just wrote — they're large. Write and move on.
7. Report: lectures filed per class, classes skipped and why, meetings pending transcript, and any deadline candidates (below).

## Lecture file format

```markdown
---
granola_id: <meeting id>
class: <class code>
date: YYYY-MM-DD
title: <meeting title from Granola>
topics: [3-6 short keywords, from the summary]
---

# <class code> — YYYY-MM-DD

<Granola's notes/summary for the meeting. Keep it as-is; don't rewrite it.>

## Transcript

<full transcript>
```

`topics` exists so agents and grep can find lectures without opening them. Keep keywords lowercase and specific ("virtual memory", "paxos"), not generic ("lecture", "discussion").

## Deadline mentions

While writing the summary section, note any concrete deadline the professor stated (assignment due dates, exam dates, quiz announcements). Then compare each one against the brain:

- Grep `due:` across that class's `assignments/*.md`. If the spoken deadline **matches** what's filed, it's not news — mention it in the report at most, flag nothing.
- If it **conflicts** with a filed assignment's `due:` (professor pushed a date back in class, Blackboard not updated yet), or names a **dated assessment with no assignment file at all**, append an entry to `inbox/blackboard-review.md` (create it with the same header `blackboard-scan.py` uses if missing). Match the scan's entry shape so one review pass handles both sources. The `## ` heading is what the phone notification shows — make it carry the whole decision in one line:

  ```markdown
  ## <today> — <CODE>: <the gist, e.g. "HW3 spoken due Sep 12, file has Sep 5" or "quiz announced for Sep 3, no file">

  In lecture <lecture date>, the professor said <what was said, briefly quoted>.
  The brain has:
  - `classes/<class>/assignments/<slug>.md` — due: <filed due>   (or: no assignment file matches)

  Options: update that file's `due:` / create an assignment file, or drop this if misheard or superseded.
  ```

- Before appending, check the review file for an existing entry saying the same thing — skip duplicates. (If the user already applied the change, the file's `due:` now matches and nothing gets flagged. If they dropped a previous flag and the professor repeats the deadline in a later lecture, re-flagging is correct — it's fresh evidence.)
- New review entries are what trigger the phone ping (when configured) — flag real conflicts, never routine mentions.

Do **not** edit any assignment file's `due:` yourself, and do **not** create Todoist tasks from lecture speech — the assignment file is the source of truth, and it changes only when the user approves the flag. Tasks get created when the actual assignment file lands in `assignments/` (see CLAUDE.md).

## Scope rules

- Only meetings inside a class's Granola folder get filed. Never pull from other folders or unfiled meetings — those belong to other projects.
- The only thing this skill writes to `inbox/` is a deadline-conflict entry in `blackboard-review.md` (above). Folder membership decides the class, so there's nothing else ambiguous to park.
