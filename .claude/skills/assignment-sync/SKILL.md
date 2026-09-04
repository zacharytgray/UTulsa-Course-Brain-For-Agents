---
name: assignment-sync
description: >
  Create Todoist tasks from assignment files in classes/*/assignments/. Use when
  the user says "sync assignments to todoist", "push deadlines to todoist", after
  adding assignment files by hand, or right after a blackboard sync. Takes an
  optional class code to sync only that class.
---

# assignment-sync

Turn assignment files into Todoist tasks. Idempotent — the task id lives in the assignment's frontmatter, so re-running is always safe.

## Steps

1. Glob `classes/*/assignments/*.md`. Skip `_template.md` and anything under `classes/_template/`. If an argument was given, keep only that class code's directory.
2. Read each class's `class.md` frontmatter for `code`, `role`, and `todoist_project` (default `School` if empty). Skip classes with `role: ta` — their assignment files are things to grade, not do; grading deadlines go in Todoist by hand.
3. Parse each assignment's frontmatter. Skip it, and say why in the report, when:
   - `status` is not `open`
   - `todoist_task_id` is already set (non-empty)
   - `due` is missing or empty
4. Run `python3 scripts/todoist-sync.py [code]` — it does the whole pass deterministically:
   creates tasks for new assignments, refreshes descriptions and due dates on existing ones,
   closes finished ones, and writes task ids back into frontmatter. Token: `TODOIST_API_TOKEN` env or
   `~/.config/todoist/token`. What it creates:
   - title: `[<CODE>] <title>` — `CODE` from `class.md`, `title` from the assignment frontmatter
   - due: date-only, even when the frontmatter has a time — homework stays off the
     calendar Todoist syncs to. Exception: `calendar: true` in frontmatter (exams,
     timed presentations) keeps the time on the task so those do land on the calendar.
   - project: the class's `todoist_project`
   - description: the repo path of the assignment file on line 1, a `Due: <date> [time]`
     line from the frontmatter, then the file's body (the
     spec). **Machine-owned, and so are the task's due date and title** — every sync overwrites
     all three from the file, so the phone app always shows the current spec and a deadline
     moved in the file (or in Blackboard, via the scan) reaches the task, as does a retitled
     assignment file. A date changed by hand in Todoist snaps
     back; the file is the only place to move a deadline. Your own notes live in task
     *comments*, which sync never overwrites or deletes.
5. The script writes ids back itself (`todoist_task_id:` line only). Commit the id changes.
   Because descriptions and due dates are refreshed on every run, re-run the sync after
   anything edits assignment files (a blackboard scan, lecture-induced spec changes, a moved
   deadline, a `calendar: true` added later) so Todoist matches.
6. Closing finished work: if an assignment has `status: submitted` or `status: graded` **and** a non-empty `todoist_task_id`, close that task. Best-effort — if the tooling can't close tasks, note it in the report and move on. Leave `todoist_task_id` in place either way.
7. Report a table: class, assignment, action (created / closed / skipped), reason for skips, task id for creates.

## Frontmatter this skill touches

```yaml
---
title: Assignment Name
due: 2026-09-01        # ISO date or datetime, local time
posted: 2026-08-25
source: ""
status: open           # open | submitted | graded
todoist_task_id: ""    # ← the only field this skill writes
calendar: true         # optional — exams/timed presentations only; puts the task on the calendar
---
```

## Scope rules

- Idempotency comes from `todoist_task_id` in frontmatter. **Never** search Todoist by title to dedupe — titles repeat across semesters and a search miss creates duplicates.
- Never create a task from a lecture transcript or a lecture summary. Deadlines spoken in class are candidates only; the assignment file is the source of truth (see CLAUDE.md).
- Never edit anything in an assignment file except the `todoist_task_id` line.
- Never delete Todoist tasks. Closing a completed one is the most this skill does.
- Never write or delete task comments — they're the user's notes zone. The sync script *reads* them
  and appends unseen ones to the assignment file under `## Notes` (deduped by comment id in an
  HTML comment marker). That read-and-mirror is the only sanctioned direction; the scheduled job
  runs it after every lecture-sync, so phone notes land in the repo within ~30 min of a run.
