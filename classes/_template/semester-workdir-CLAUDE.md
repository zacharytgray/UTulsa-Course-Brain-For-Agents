# Coursework — <Semester>

<!-- Template for the CLAUDE.md that goes at the semester root of the workdir tree
     (Coursework/<semester>/CLAUDE.md), not in this repo. Copy it there once per semester,
     fill in the blanks, delete this comment. -->

You are on the files side of the course-brain system: this tree holds the coursework files,
and your clone of the course-brain repo holds the text and tooling. The repo's full rulebook
applies here and is imported below — read it as if you were in the repo.

@_course-brain-rules.md

(That file is a machine-synced copy of the repo's CLAUDE.md, refreshed by the scheduled
sync job — never edit it here; edit `CLAUDE.md` in the repo instead.)

## What's different when you're here (and only this)

- **Slash commands aren't registered in sessions opened here.** The skills the rulebook
  mentions (`/blackboard-sync`, `/lecture-sync`, `/assignment-sync`, `/digest`) live as
  plain instruction files at `.claude/skills/<name>/SKILL.md` in the repo. To do a sync
  task, read the matching SKILL.md and follow it exactly as if invoked.
- **Repo-relative paths in the imported rules** (`scripts/check.py`, `classes/<class>/…`,
  `inbox/…`) resolve from the repo clone, not from here.
- **`git pull` in the repo before answering questions about repo state** (synced lectures,
  filed assignments, flags). The scheduled job commits and pushes on its own schedule; what
  looks missing is usually unpulled. If you change anything in the repo, lint, commit, and
  push it.
- Each class folder here is that class's `workdir` from the rulebook. Its own CLAUDE.md
  carries the class specifics (code, schedule, role, assignment notation).
