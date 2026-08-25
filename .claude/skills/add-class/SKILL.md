---
name: add-class
description: >
  Set up a new class directory in this repo from the template — class.md
  frontmatter, Granola folder wiring, and the sync schedule. Use when the
  user says "add a class", "new class", "set up <code>", or gives a class code
  plus a course name for a course that isn't in classes/ yet.
---

# add-class

Create `classes/<code lower>/` from the template and wire it up. One class per run.

## Steps

1. **Collect the details.** Ask for everything missing in a single message, then wait:
   - `code` (e.g. `CS-2123`) and `name`
   - `role`: `student` (default) or `ta` if the user is teaching it
   - `professor`, and their email if known
   - `schedule` — days from `MTWRF` (R = Thursday), 24-hour `HH:MM-HH:MM`, comma-separated
     segments for split weeks: `MW 10:00-11:15, F 9:00-9:50`. Reject anything that doesn't
     match that shape; don't guess at "10-11" or "TTh".
   - `blackboard_url` — the course's url on Harvey
   - `semester`, `starts`, `ends` only if they differ from the template defaults (Fall 2026,
     2026-08-24 to 2026-12-11). Check the template's current values first — if they're for a
     past term, ask.

2. **Copy the template.** `cp -r classes/_template classes/<code lower>` — the directory name is
   the lowercased code (`CS-2123` → `classes/cs-2123/`). Fill in the class.md frontmatter; `code`
   keeps the uppercase form. Replace the `CS-XXXX — Class Name` heading in the body with the real
   code and name, and leave the rest of the body alone.

3. **Find the Granola folder.** Call `list_meeting_folders`.
   - Exactly one folder title contains the code: write its id into `granola_folder_id`.
   - No match: leave `granola_folder_id` empty and tell the user to create a folder named
     `<CODE> — <name>` in the Granola app. lecture-sync matches it by title on the first run
     and fills the id in itself.
   - Several match: list them and ask which one. Don't pick.

4. **Verify.** Run `python3 scripts/gen-schedule.py --dry-run` and `python3 scripts/check.py`.
   Fix any problems and re-run. Warnings are fine — the empty `granola_folder_id` warning is
   expected when the folder doesn't exist yet.

5. **Report** what was created, plus the manual steps left for the user:
   - create the Granola folder, if step 3 didn't find one
   - drop the syllabus into `classes/<code lower>/syllabus.md` when it arrives
   - commit (and push, if the repo has a remote) — the scheduled sync job regenerates its
     schedule at the next 07:05 weekday run. To make it immediate, run
     `python3 scripts/gen-schedule.py` on the machine that runs the sync.

## Notes

- Don't create the Granola folder yourself — the MCP is read-only.
- Don't commit or push. The user does that.
