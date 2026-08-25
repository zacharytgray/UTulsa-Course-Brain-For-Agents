# UTulsa Course Brain

Central repo for all class content: lecture transcripts, syllabi, assignments, materials. Design in [docs/VISION.md](docs/VISION.md), how to add a class in [docs/ADDING-A-CLASS.md](docs/ADDING-A-CLASS.md), automation runbook in [docs/OPERATIONS.md](docs/OPERATIONS.md), swapping tools in [docs/ADAPTING.md](docs/ADAPTING.md).

## Layout and conventions

- Each class lives in `classes/<code-lowercase>/` (e.g. `classes/cs-2123/`). `class.md` frontmatter has `role` (student | ta), the Granola folder id, Blackboard url, schedule, and start/end dates. TA classes: lectures sync as usual, but assignment files are things to grade, not do. `classes/_template/` is the canonical shape.
- Lectures: `classes/<class>/lectures/YYYY-MM-DD.md` (`-2`, `-3` suffix if a class meets twice in a day). Frontmatter carries `granola_id`, `class`, `date`, `title`, `topics`. Summary at the top, full transcript below a `## Transcript` heading.
- Assignments: `classes/<class>/assignments/<slug>.md`, frontmatter `title`, `due`, `posted`, `source`, `status` (open | submitted | graded), `todoist_task_id`. Spec as the body. Attachments beside as `<slug>.<ext>`. Template at `classes/_template/assignments/_template.md`.
- Materials and any downloaded files live OUTSIDE this repo, in the class's `workdir` (see class.md frontmatter) under `materials/` — e.g. a cloud-synced `Coursework/<semester>/<name>/` folder. The repo holds text only: specs, syllabi as markdown, transcripts. `classes/<class>/materials/` stays for the rare text-native artifact. Each workdir also has `homework/`, `exams/`, and `projects/` for the user's own working files (plus `grading/` in TA classes) — file downloads and deliverables into the matching subfolder, not the workdir root.
- Inside `homework/`, each assignment gets its own subfolder named by that class's own assignment notation — a class using `L00`, `L01`, … gets those; a class whose assignments are "Homework 1" would use `homework-1`. Downloaded files keep their original names but live in the assignment's subfolder, since filenames rarely match the organizational scheme and one assignment can involve several files. Same idea for `exams/` and `projects/` when a class has more than one.
- `inbox/`: flat holding area for manual exports or anything not handled by a sync flow. If you file one, move it to the right class.
- Past semesters go to `archive/<semester>/`.

## Skills

- `/add-class` — scaffold a new class (see ADDING-A-CLASS.md for the full process incl. the manual steps).
- `/lecture-sync [code]` — pull new lectures from Granola class folders. Idempotent: lecture files carry a `granola_id` and filed ones are skipped. If a scheduled sync job is installed (docs/OPERATIONS.md), it also runs automatically 30 min after each scheduled class — **pull (or check the log) before assuming lectures are missing**.
- `/blackboard-sync [code]` — pull new assignments/materials from Blackboard. Auth is scripted via `scripts/bb login` (password manager + TOTP); the agent never types credentials itself.
- `/assignment-sync [code]` — create Todoist tasks for assignment files without one.
- `/digest [days]` — weekly summary across classes plus what's due.

## Reading discipline

- **Read summaries first, transcripts only when needed.** Full transcripts are long; don't load them into context by default. Stop at `## Transcript` unless the question needs the actual words.

## When helping with assignments

- Pull the assignment spec from `classes/<class>/assignments/`, then the lectures it builds on (check dates and `topics` in lecture frontmatter).
- Help the user understand and do the work; follow their professor's AI policy for anything that gets submitted.

## Todoist

- Only assignment *files* in `assignments/` get Todoist tasks, titled `[<class code>] <assignment title>` with the due date. Deadlines merely spoken in lecture are flagged for review, never auto-created — the assignment file is the source of truth.
- Before creating a task, check the file's `todoist_task_id`; record the id there after creating. Never dedupe by searching Todoist titles.
- Tasks are created **date-only** (no due time) so homework stays off the calendar Todoist syncs to. The due time is kept in the file's `due:` frontmatter and surfaced in the task description's `Due:` line. Exception: files with `calendar: true` (exams, timed presentations) keep the time on the task, so those do land on the calendar.
- Every sync re-sends the task's due date from the file, so a deadline moved in the file (or a `calendar: true` added later) propagates to Todoist — and a date changed by hand in Todoist snaps back. The file is the only place to move a deadline.

## Flags (pending decisions)

- `inbox/blackboard-review.md` is the pending-decisions file — entries from the Blackboard scan plus deadline conflicts spoken in lecture. Each entry is self-contained: heading states the decision, body has the evidence and options.
- If the user references a notification, ping, or flag — even tersely ("responding to the notification — yes that's fine") — pull, then read `inbox/blackboard-review.md`; the newest entries are what they mean. Apply or drop each per their answer, delete handled entries, run `python3 scripts/check.py`, commit and push. Todoist reconciles on the next scheduled run.
- The ping only fires after a successful push (or, with no remote configured, after the commit), so the repo being opened always already holds every flag being responded to.

## Granola

- Only meetings in class-specific Granola folders belong here. Other Granola meetings are managed elsewhere — leave them alone.

## How to verify

```bash
python3 scripts/check.py
```

Lints every class, lecture, and assignment file. Run it before committing class or assignment changes. `python3 scripts/gen-schedule.py --dry-run` previews the sync schedule without installing anything (safe on any machine).
