# Workflows

How an agent actually uses this repo, and five things worth asking it for. [VISION.md](VISION.md) is why the repo is shaped this way, and [OPERATIONS.md](OPERATIONS.md) is the runbook for the automated parts. This doc is the part in between, what happens when you open a session and ask for something.

## How an agent loads this repo

In rough order, this is what an agent has in front of it before you've asked anything.

1. **`CLAUDE.md`**, the rulebook. Where content lives, the file conventions, the task-manager rules, the flags file, the reading discipline. `AGENTS.md` is a symlink to the same file, so an agent that looks for that name gets the identical context. There is one copy, so the two can't drift.
2. **The skill files**, `.claude/skills/<name>/SKILL.md`. Claude Code registers these as slash commands. Any other agent reads the file and follows the steps.
3. **`classes/*/class.md`**, the per-class wiring. Code, name, role, schedule, semester dates, Blackboard url, lecture-source folder id, task project, and `workdir`, which is where that class's real files live.
4. **Whatever the question needs**, found by frontmatter rather than by reading everything.

A session opened in a class's coursework folder instead of the repo gets the same rulebook a different way. The scheduled job copies `CLAUDE.md` into every workdir and semester root as `_course-brain-rules.md`, and the workdir's own `CLAUDE.md` imports it. That copy is machine-owned. Edit the rulebook in the repo, never in a workdir.

## Frontmatter is the query surface

Every file carries the fields that make it findable, so most questions are a grep and a couple of reads instead of a scan of the semester.

Lecture frontmatter:

```yaml
granola_id: <stable id>   # or source_id, for anything filed by lecture-import.py
class: CS-2123
date: 2026-09-04
title: Hash tables
topics: [hashing, collision resolution, load factor]
```

Assignment frontmatter:

```yaml
title: "HW3: Hash Tables"
due: 2026-09-18T23:59
posted: 2026-09-04
source: "https://harvey.utulsa.edu/ultra/courses/_12345_1/outline"
status: open              # open | submitted | graded
todoist_task_id: "..."
calendar: true            # optional, exams and timed presentations only
```

Which gives you queries like these:

```bash
# everything still open, across all classes
grep -l '^status: open' classes/*/assignments/*.md

# what's due, sorted, with the file it came from
grep -H '^due:' classes/*/assignments/*.md | sort -t: -k3

# lectures that covered a topic
grep -rl 'topics:.*hashing' classes/*/lectures/

# what the mirror has for one class
ls "$(grep '^workdir:' classes/cs-2123/class.md | cut -d' ' -f2- | tr -d '"')/harvey"
```

`topics` exists for exactly this. It's written from the summary at file time, lowercase and specific, so an agent can find the right three lectures without opening thirty.

## Reading discipline

A lecture file is a short summary followed by a full transcript under a `## Transcript` heading. A semester of transcripts will not fit in a context window, and loading them by reflex is the main way an agent wastes a session.

The rule is to read down to `## Transcript` and stop, unless the question needs the professor's actual words. In practice:

```bash
grep -n '^## Transcript' classes/cs-2123/lectures/2026-09-04.md
```

then read the file with a line limit just under that number. If the grep finds nothing, the file is malformed and worth flagging. Go below the heading when you need a quote, an exact definition, or something the summary clearly dropped, and go straight to the relevant part rather than reading the whole thing.

## The repo holds text, the workdir holds files

This split trips people up once and then never again.

- **In the repo**: assignment specs, syllabi as markdown, lecture transcripts, quiz and test question text, and the scan and mirror manifests. Text only.
- **In the workdir**, a cloud-synced `Coursework/<semester>/<class>/` folder named by the class's `workdir:` line: everything else.

Inside a workdir:

| Folder | Owner | What's in it |
|---|---|---|
| `harvey/` | `scripts/blackboard-mirror.py` | every file posted on Blackboard, in Blackboard's folder structure, plus Ultra page text as markdown. Pruned to match Blackboard, so nothing should be hand-placed here. Safe to delete and regenerate. Rename it with `CB_MIRROR_DIRNAME`. |
| `homework/` | you | one subfolder per assignment, named in that class's own notation |
| `exams/` | you | study guides, practice, your own exam work |
| `projects/` | you | project work |
| `materials/` | you | files that aren't on Blackboard, like a syllabus PDF that arrived by email |
| `grading/` | you | TA classes only |

The sync never touches the five folders that are yours. When an agent helps with homework, it reads from `harvey/` and writes into `homework/<assignment>/`.

## Flags, the one place decisions wait

`inbox/blackboard-review.md` is the pending-decisions file. Entries come from three sources. The Blackboard scan writes one when a graded column is ambiguous or has no due date. The mirror writes one when an assignment's spec text changed on Blackboard after you edited the file. The lecture flow writes one when a deadline spoken in class contradicts a filed `due:`.

Every entry is self-contained. The `## ` heading states the decision in one line, which is also what a phone notification shows, and the body carries the evidence and the options. Nothing in the file has been applied. Handle an entry, then delete it. Entries stay until you do.

If you mention a notification or a flag to an agent, even briefly, the right move is to pull first and read this file, because the newest entries are the ones you mean. The ping only fires after a successful push, so a repo you open from a ping already contains the flag.

## Five workflows

### Homework help

> "Help me start HW3 for CS-2123."

**Reads.** `classes/cs-2123/assignments/hw3-hash-tables.md` for the spec and the deadline. Then `class.md` for the `workdir`. Then the lectures the assignment builds on, found by date and `topics`, summaries first. Then the slide decks in the assignment's module inside the workdir's `harvey/`. Reading the whole module folder rather than only the one deck the spec names is the point. The answer to a homework question is usually in a neighboring deck.

**Writes.** Nothing in the repo. Drafts, code, and deliverables go to the workdir's `homework/<assignment>/`, using that class's own assignment notation for the folder name.

**Needs you.** Your professor's AI policy governs anything you submit. And when you turn it in, flip the file's `status` to `submitted` and end it with a `## Submitted` section listing the workdir-relative paths you handed in, or the posted text itself for a discussion post. Checking the task off in your task manager does that flip for you on the next sync.

### Exam prep

> "Make me a study guide for the CS-2123 midterm from the last three weeks."

**Reads.** The exam's assignment file for the date, format, and any posted scope. Every lecture file in the window, summaries only. Transcripts only where a summary is too thin to be useful, or when you ask something like "what did she emphasize more than once", which needs the actual words. Slides and review sheets in `harvey/`.

**Writes.** The study guide wherever you want it, normally the workdir's `exams/`. Nothing in the repo changes.

**Needs you.** Judging what's actually on the exam. The repo knows what was said and what was posted, and neither is the same as what will be tested.

### Catching up on a missed lecture

> "I missed Tuesday's CS-2123 lecture, catch me up."

**Reads.** `classes/cs-2123/lectures/2026-09-04.md`, summary only, plus the lecture before it for continuity. If a topic sits in the transcript and not the summary, the transcript for that section.

**Writes.** Nothing. This one is a conversation.

**Needs you.** Nothing, if the recording happened. If it didn't, no amount of tooling recovers a lecture nobody recorded. This is the reason for the first-week transcription-quality check in [ADDING-A-CLASS.md](ADDING-A-CLASS.md).

### Weekly digest

> "/digest" or "/digest 14"

**Reads.** Every `class.md` for code, name, and role. Every lecture file whose filename date falls in the window, summaries only. Every assignment's frontmatter, keeping the open ones due in the next two weeks or already past.

**Writes.** Nothing. The digest goes to chat. The skill is explicitly read-only, no file writes, no task-manager calls, no git.

**Needs you.** The Flags section at the bottom. It surfaces deadlines mentioned in a lecture summary with no matching assignment file, transcripts that came out empty or garbled, and assignments past due that are still `status: open`. The digest names them and stops there on purpose.

### Handling a phone ping

> "Process the blackboard review file." Or, tersely, "responding to the notification, yes that's fine."

**Reads.** `inbox/blackboard-review.md`, after a `git pull`. Then the assignment files each entry names, so the current `due:` and body are in front of you before you decide.

**Writes.** Only what you approved. A `due:` line updated, a new assignment file created, or nothing at all if you drop the entry. Then the handled entries get deleted from the review file, `python3 scripts/check.py` runs, and the change is committed and pushed. Your task manager reconciles on the next scheduled run, or immediately with `python3 scripts/todoist-sync.py cs-2123`.

**Needs you.** The whole thing. Every entry in that file exists because a script refused to guess.

## Using it with other agents

The repo is markdown and Python, so nothing here is Claude-specific except which files an agent looks for by default.

**Codex.** `AGENTS.md` is a symlink to `CLAUDE.md`, so Codex picks up the same project context with no extra setup. Skills aren't slash commands there; point it at the file, as in "read `.claude/skills/digest/SKILL.md` and follow it". For the scheduled job, set `CB_LECTURE_SYNC_CMD` to your Codex invocation.

**Hermes.** Same story. It reads `AGENTS.md`, and skills are files you tell it to follow. Personas and tool permissions are configured on the Hermes side, outside this repo. If you want a scheduled run, `CB_LECTURE_SYNC_CMD` takes any command string.

**Plain Claude CLI.** `claude -p "/lecture-sync"` is the default the scheduled job uses, and any skill runs the same way. `CLAUDE_BIN` points the job at the binary when it isn't on the job's `PATH`, which is normal under launchd.

**No agent at all.** The Python scripts don't need one. `blackboard-scan.py`, `blackboard-mirror.py`, `todoist-sync.py`, `lecture-import.py`, `gen-schedule.py`, and `check.py` all run standalone, and `CB_LECTURE_SYNC_CMD=none` drops the agent stage out of the scheduled job. You lose lecture transcription and the deadline-conflict flagging that lives in the lecture-sync skill. Everything else keeps working.
