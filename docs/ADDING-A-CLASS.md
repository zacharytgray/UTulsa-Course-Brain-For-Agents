# Adding a class

This is the ingestion process for a new course. Do it once per class, ideally the day the syllabus arrives. Steps marked **(you)** can't be automated; everything else the agent does via `/add-class`.

## Before you start

- **Paid Granola seat.** Transcript access through the MCP is paid-only, and free-tier history expires after 30 days. Without it lectures are silently lost.
- **Recording policy.** Check whether your school or the professor requires permission to record. Do this once per class, before the first lecture.

## The steps

1. **(you) Create the Granola folder.** In the Granola app, make a folder named `<CODE> — <class name>`, e.g. `CS-2123 — Data Structures`. The MCP is read-only, so this can't be scripted. The code in the title is what lets the agent match it.

2. **Run `/add-class`** in Claude Code inside this repo, giving it the code, name, professor, schedule, and Blackboard url. Say if you're the TA (`role: ta`): lectures still sync, but assignment files are treated as things to grade — `/assignment-sync` skips them and `/digest` lists them under "To grade".

   You don't need the syllabus to do this step — only the schedule and the Blackboard url (leave it blank if the course is still locked). It will:
   - copy `classes/_template/` to `classes/<code-lowercase>/` and fill in `class.md`
   - look up the Granola folder id and write it in
   - validate the schedule format and lint the repo (`scripts/check.py`)
   - tell you what's still manual

   Schedule format: days `MTWRF` (R = Thursday), 24-hour times, `MWF 10:00–10:50`. Several segments are fine: `TR 13:00-14:15, F 9:00-9:50`.

   If the class requires an initial discussion post before the reply deadline, set `discussion_initial_post:` to that weekday (e.g. `friday`). Each discussion is then filed as two assignments instead of one; leave it empty otherwise.

   The copied `assignments/_template.md` and `materials/README.md` are references; every skill and `check.py` skips them, so leave them or delete them. `workdir-CLAUDE.md` and `semester-workdir-CLAUDE.md` come along too — they belong in the workdir, not the class dir (step 3), so delete them from the copy once you've placed them.

3. **(you) Syllabus.** Paste it into `classes/<class>/syllabus.md`. The original PDF goes in
   the class's `workdir` under `materials/` (set `workdir:` in class.md — e.g. a cloud-synced
   `Coursework/<semester>/<name>/` folder), not in this repo. Everything posted on Blackboard
   arrives on its own in the workdir's `harvey/` — that folder is the mirror, built by
   `scripts/blackboard-mirror.py`, so don't put anything in it by hand.

   Also drop a `CLAUDE.md` in the workdir, from `classes/_template/workdir-CLAUDE.md`, so
   agent sessions opened in the class folder know about the system. The shared rules live
   in `Coursework/<semester>/CLAUDE.md` — created once per semester from
   `classes/_template/semester-workdir-CLAUDE.md` — and cover everything a repo session
   knows (skill instructions by path, pull-first rule, common asks); the per-class file
   only carries the code, schedule, role, and assignment notation. Both import
   `_course-brain-rules.md`, a copy of this repo's CLAUDE.md that the scheduled job
   refreshes in every workdir and semester root (Claude's `@import` can't reach outside the
   project directory, which is why it's copied rather than linked).

4. **(you) Commit** (and push, if your copy has a remote). The agent doesn't commit. Run `python3 scripts/check.py` first if you edited anything by hand. The scheduled job regenerates its own schedule at the next 07:05 weekday run; to make it immediate, run `python3 scripts/gen-schedule.py` on the machine that runs the sync.

That's it. From then on:

## What happens automatically

- **You hit record in Granola at the start of each lecture**, inside the class folder (or move the note into it afterward). Recording is manual-start; nothing auto-starts.
- **30 minutes after the class ends**, the scheduled job runs `/lecture-sync`, files the transcript at `classes/<class>/lectures/YYYY-MM-DD.md`, and commits. If the Blackboard poll job is installed, it checks Blackboard every 30 minutes in between.
- Summaries at the top, full transcript below `## Transcript`.

## First-week checks

Do these after the first real lecture, once, per class:

- The lecture file exists and the `granola_id` in its frontmatter matches the Granola note.
- Read the summary. Is the transcription good enough? Lecture halls are harsher than meetings. If it's bad, move the laptop/mic closer or record from a phone — the pipeline can't fix bad audio.
- The job log (`~/Library/Logs/course-brain/lecture-sync.log`) shows the run and no errors. See [OPERATIONS.md](OPERATIONS.md).

## As the semester goes

| When | Do |
|---|---|
| Something is posted on Blackboard | `/blackboard-sync <code>` (login is scripted via `scripts/bb login`; the agent files it) |
| New assignment file lands in `assignments/` | `/assignment-sync` creates the Todoist task |
| Sunday evening / Monday morning | `/digest` for the week that was and what's due |
| Working on homework | Just ask; the agent reads the spec and the relevant lectures |
| A lecture didn't get filed | `git pull` first. Then `/lecture-sync <code>` manually. Then check the job log. |

## Semester end

Move `classes/*` to `archive/<semester>/` (e.g. `archive/fall-2026/`) and reset `classes/` to just `_template/`. The job's schedule will already have stopped (each class's `ends` date), and `check.py` ignores `archive/`.
