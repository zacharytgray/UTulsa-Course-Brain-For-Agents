# Vision

A "course brain": every lecture, syllabus, assignment, and course document for the semester lives in one repo, structured so an agent can use all of it. The end state is being able to say "help me with this homework" and have the agent already know the lectures, the assignment spec, the professor's conventions, and what's due when.

## Why markdown, not an app

Decision: **markdown-first, no app.**

- The consumer of this data is an agent, not a UI. Agents are already great at navigating a well-structured file tree; an app would just wrap that in friction.
- Git gives history, sync across your machines, and zero infrastructure.
- Every piece (Granola MCP, browser tools, Todoist) already plugs into Claude Code. An app would have to re-integrate all of it.
- If a UI ever earns its keep (e.g. a semester dashboard), it can be a static site generated *from* the markdown. The data layer doesn't change.

## The pipeline

```
Granola (record lecture, folder per class)
   │  /lecture-sync skill (auto via the scheduled job 30 min after class; manual any time)
   ▼
classes/<class>/lectures/YYYY-MM-DD.md   ← summary + full transcript
   │
Blackboard / Harvey (scripted login + API scan + mirror; browser skill as fallback)
   ▼
classes/<class>/assignments/ + syllabus.md   (files → workdir harvey/)
   │  deadline extraction
   ▼
Todoist (one project per class, or one School project)
```

### Lecture sync

- Each class gets a Granola folder. The folder id lives in the class's `class.md`. Folder creation is manual (the MCP is read-only) — step 1 of [ADDING-A-CLASS.md](ADDING-A-CLASS.md).
- The `/lecture-sync` skill (in `.claude/skills/`) lists meetings in each class folder, pulls transcript + summary via the Granola MCP, and writes one file per lecture.
- **Idempotency lives in the repo, not in sync state.** Each lecture file's frontmatter carries the `granola_id`; the skill skips any meeting id already filed. No last-sync timestamps to track or corrupt, and re-running is always safe. This falls out of the MCP being read-only — Granola can't be marked "processed", so the repo is the ledger.
- Folder membership decides the class, so this skill never needs `inbox/`. The inbox stays as a fallback for other flows (e.g. manual exports).
- **Scheduling note (verified 2026-08):** claude.ai connectors do **not** reach headless CLI runs — `claude mcp list` in a scheduled job shows only locally-configured servers. So hands-free sync needs the official Granola remote MCP (`https://mcp.granola.ai/mcp`) added to the CLI config of the machine that runs the job, with a one-time OAuth there. Everything else is automated.

### Hands-free sync

The scheduled job runs `/lecture-sync` 30 minutes after each class ends, on a launchd schedule generated from every class's `schedule:` line, and commits (and pushes, if the repo has a remote). It's self-updating: change a class's schedule and the job regenerates its own schedule on the next run. A second, optional launchd job polls Blackboard every 30 minutes between 07:00 and 23:00, so a column posted during an evening class doesn't wait for the next class to be noticed; both jobs run the same script from the scan onward. Details, log locations, and the troubleshooting table are in [OPERATIONS.md](OPERATIONS.md).

### Blackboard sync

- Two layers. `scripts/blackboard-scan.py` (part of the scheduled job) diffs the gradebook and content tree through Blackboard's JSON API: new graded assignments get filed, moved due dates get fixed, anything ambiguous gets flagged to `inbox/blackboard-review.md` for a human decision. A graded column with no due date is flagged rather than filed, since only you can decide what deadline it should carry. The `/blackboard-sync` skill covers the rest interactively — browsing content, syllabi, downloads.
- **Login is scripted.** `scripts/blackboard.py` runs the whole Entra SSO flow in Playwright, with the username, password, and TOTP pulled from a password-manager item. The agent never handles the raw credentials — the script does, and the saved session lives in `~/.course-brain/bb-state.json`, outside the repo. This is what makes scheduled, unattended Blackboard scans possible.
- **Everything is mirrored.** `scripts/blackboard-mirror.py` pulls each class's whole content tree into the workdir's `harvey/`, and spec text into the assignment files. Ultra pages (text posted straight on Blackboard, with no file to download) are rendered to markdown and mirrored beside the files, so that text exists locally too. The point is that an agent helping with homework has the slides on hand instead of fetching them mid-task.
- **`harvey/` is script-owned**, which is what makes that safe. It's regenerated and pruned to match Blackboard; your own folders (`materials/`, `homework/`, `exams/`, `projects/`, `grading/`) are never touched by the sync. Nothing hand-placed can be lost to a prune, and the mirror can be deleted and rebuilt without thinking about it.

### Todoist

- When a new assignment file lands in `assignments/` (from a Blackboard scan or by hand), the sync creates a Todoist task with the deadline and the full spec in the description.
- Deadlines *spoken in lecture* ("exam moved to Friday") are flagged as candidates, not auto-created — transcribed speech is too noisy to write to Todoist unreviewed. The assignment file is the single source of truth for task creation.
- Convention to prevent duplicates: task title `[<class code>] <assignment name>`, and record the created task id in the assignment's frontmatter so syncs are idempotent.

## Per-class structure

`classes/_template/` is the canonical shape; the class directory is the lowercase code (`classes/cs-2123/`). `class.md` frontmatter holds the wiring:

```yaml
---
code: CS-2123
name: Data Structures
role: student        # or ta
professor: Dr. ...
professor_email: ...
granola_folder_id: "..."
blackboard_url: "..."
todoist_project: School
schedule: MWF 10:00–10:50
semester: Fall 2026
starts: 2026-08-24   # first-run sync range begins here
ends: 2026-12-11     # the job stops scheduling class runs after this
discussion_initial_post: friday   # optional; see below
---
```

`discussion_initial_post` is for classes that want an initial post before the reply deadline. Discussions are recognized by their Blackboard item type, so with that line set the scan files each one as a pair: `Discussion: <topic>` due 23:59 on the named weekday, `Discussion Reply: <topic>` on the gradebook's date. Without it, one assignment.

Assignments are `assignments/<slug>.md` with frontmatter (title, due, posted, source, status, todoist_task_id, optional calendar) and the spec as the body — see `classes/_template/assignments/_template.md`. A submitted one ends with a `## Submitted` section: workdir-relative paths for file deliverables, or the posted text itself for a discussion post.

Course files don't live in the repo. Every Blackboard file — slides, PDFs, media — is mirrored into the class's `workdir` (`workdir:` in `class.md`) under `harvey/`, keeping Blackboard's folder structure. The repo holds text only. `scripts/blackboard-mirror.py` builds and refreshes the mirror; the workdir's `materials/` stays for files you place by hand, and `classes/<class>/materials/` in the repo holds the rare text-native artifact.

**Adding a class** is its own doc: [ADDING-A-CLASS.md](ADDING-A-CLASS.md). Short version: create the Granola folder, run `/add-class`, paste the syllabus, commit.

## What the brain unlocks (beyond filing)

- **Homework help with real context**: the agent reads the assignment spec plus the exact lectures it builds on.
- **Exam prep**: generate a study guide from the last N lectures; ask "what topics has she emphasized twice?"
- **Weekly digest**: what happened in each class this week, what's due next week.
- **Cross-class connections**: "this week's ML lecture used the same math as the optimization homework."
- **Catch-up mode**: miss a lecture, read a 5-minute summary generated from your own recording.

## Granola facts (verified 2026-08 against official docs)

- Plans: Basic (free, history limited to last 30 days), Business ($14/user/mo, "unlimited meeting notes and history"), Enterprise. **This system needs a paid seat**: raw transcript access via the MCP (`get_meeting_transcript`) is paid-only, and 30-day history on free would silently lose lectures.
- In-person recording works: Granola captures mic audio through the OS; no meeting link or calendar event required. Start via "+ New Note".
- Recording is manual-start only — hitting record at the start of each lecture is required; nothing auto-starts.
- **Audio is not retained.** Desktop transcribes in real time and never stores audio. The transcript is the only artifact — no re-listening later. Filing transcripts here promptly is the archive.

## Things to check for your own setup

- Real-classroom transcription quality: lecture halls (distance to speaker, echo, crosstalk) are harsher than meetings. Test one real lecture before trusting it.
- Recording permission: recording lectures may need instructor permission depending on your school's policy. Ask once per class, before the first lecture.
- Blackboard layout varies by course and instructor. The `/blackboard-sync` navigation steps are a starting procedure — expect to adjust them after first contact with your real course pages, then update the skill.
- Transcript size: a semester of full transcripts is fine for git, but agents shouldn't read whole transcripts by default — summaries first, transcript on demand. Enforced by convention in CLAUDE.md and the digest skill; not by tooling.

## Skills

All in `.claude/skills/`. Each is a procedure the agent follows; none holds state outside the repo.

| Skill | What | Runs where |
|---|---|---|
| `/add-class` | scaffold a class dir, wire Granola folder, validate | interactive |
| `/lecture-sync [code]` | file new Granola lectures | scheduled job + interactive |
| `/blackboard-sync [code]` | pull new assignments/materials from Blackboard; auth via `scripts/bb login` | interactive; the scheduled job covers the routine part via `blackboard-scan.py` + `blackboard-mirror.py` |
| `/assignment-sync [code]` | create Todoist tasks for assignment files that don't have one | interactive |
| `/digest [days]` | what happened this week, what's due | interactive |

`scripts/check.py` lints the whole repo (frontmatter, schedules, lecture/assignment shape, stray merge-conflict markers). Run it before committing class changes. `scripts/test_blackboard_scan.py` covers the scan's parsing and diff logic.
