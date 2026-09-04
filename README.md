# UTulsa Course Brain (for agents)

Your AI can't help you with school if it can't see your school. This repo is my fix for that. It's a template for a "course brain", one git repo that holds a semester of TU coursework as structured markdown. Lecture transcripts, syllabi, assignment specs, due dates. Point an agent at it and the agent already knows what your professor said on Tuesday, what HW3 actually asks for, and what's due this week. I built it for my own classes and cleaned it up to share, because I think every student here should have one. Reign 'Cane. 💙

## What this is, and what it is not

Three things, and that's all:

- A **repo layout** for classes, lectures, and assignments, with a linter (`scripts/check.py`) that enforces it.
- **Scripts** that log into Blackboard, scan it, mirror it, sync your task manager, and install a schedule.
- **Skill files**, markdown procedures in `.claude/skills/` that an agent reads and follows.

It is not an agent. Nothing in here thinks. It is the knowledge base and the plumbing, and whatever agent you run does the reasoning. Claude Code, Codex, and Hermes all work, because the project context is plain markdown and the skills are plain procedures.

If you saw NEPTR at a talk, NEPTR is not in this repo. NEPTR is a Hermes agent with a persona and a tool-permission set I wrote, pointed at my private copy of this template. The persona, the Hermes configuration, my own semester repo, and the machine it runs on all live somewhere else. What's here is the part that transfers to you.

There is also no course data in here. Clone it and `classes/` holds one `_template/`, plus `examples/cs-2123/` as a synthetic class you can copy in to see the shape. Your copy fills up with your schedule, your professors' words, and your coursework, so make it private and keep it that way.

## What it does

- **A local copy of Harvey that stays current.** A scheduled scan reads the gradebook and content tree through Blackboard's JSON API and files every graded item as a markdown assignment file with its title, due date, and source url. When a professor moves a due date on Harvey, the file updates itself on the next run. The repo ships with a working Harvey API map (`.claude/skills/blackboard-sync/SKILL.md`) covering the endpoints, the auth flow, and the gotchas.
- **A 30-minute poll, so an evening posting doesn't wait until tomorrow.** A second scheduled job runs the same scan every 30 minutes between 07:00 and 22:59, and stays silent outside those hours. The scan is a few requests per class so it runs every time. The heavier file mirror only runs when the scan saw a change or the last mirror is over two hours old. `python3 scripts/gen-schedule.py --no-poll` skips this job entirely.
- **Agents can reach Harvey without you in the browser.** Login is scripted with Playwright, your password manager, and TOTP, so a scheduled job or an interactive agent can pull a spec or check for new postings unattended. The agent never sees your password. The session cookie file lives at `~/.course-brain/bb-state.json`, mode 600, outside the repo.
- **Course files land next to the work.** `scripts/blackboard-mirror.py` pulls each class's whole content tree into that class's workdir under `harvey/`, keeping Blackboard's folder structure. Ultra pages, the ones that are text posted straight on Blackboard with no file to download, are rendered to markdown and mirrored beside the files. Assignment spec text is filled into the assignment file, and if that spec later changes on Blackboard your edited body is flagged for review rather than overwritten. Quiz and test question text is appended under `## Questions` where Blackboard will serve it.
- **Every lecture, filed.** Hit record in [Granola](https://granola.ai) at the start of class. Thirty minutes after class ends, the scheduled job files the transcript and summary at `classes/<class>/lectures/YYYY-MM-DD.md`. Not a Granola user? `python3 scripts/lecture-import.py cs-2123 lecture.txt --date 2026-09-04` files a transcript from any source into the same format.
- **Deadlines flow to your task app, and completion flows back.** Each assignment file becomes a task with the full spec in the description. Every run re-sends the title, description, and due date from the file, so the phone always shows the current spec. Check a task off and the next run flips the file to `status: submitted` and writes a `## Submitted` section; mark the file submitted or graded and the next run closes the task. Comments you leave on a task get mirrored into the file under `## Notes`. Exams marked `calendar: true` keep their due time, so those land on the calendar; homework is created date-only so it doesn't.
- **Discussions get filed the way they're actually due.** They're recognized by their Blackboard item type, not by a "Discussion" in the title. Set `discussion_initial_post: friday` in a class and each discussion is filed as two assignments, an initial post due that weekday and a reply on the gradebook's date, so the two tasks read correctly on your phone.
- **It catches what Blackboard doesn't say.** When a professor says "push that to Friday" in lecture, the lecture flow compares it against the filed due date and writes the conflict to `inbox/blackboard-review.md` for your decision, with an optional phone ping via [ntfy](https://ntfy.sh). Nothing changes until you say so.
- **Weekly digest.** `/digest` reports what each class covered, what's due, and what needs a look.

## How an agent uses it

- **`CLAUDE.md` is the project context, and `AGENTS.md` is a symlink to it.** Any agent that reads either one gets the same rulebook, covering where content lives, the file conventions, the task-manager rules, the flags file, and the reading discipline. There is one copy, so the two can't drift.
- **Frontmatter is the query surface.** Lectures carry `class`, `date`, `title`, `topics`, and an id (`granola_id` or `source_id`). Assignments carry `title`, `due`, `posted`, `source`, `status`, and `todoist_task_id`. That means "what's open and due in the next two weeks" is a grep, not a database.
- **Skills are procedures, not code.** `.claude/skills/<name>/SKILL.md` spells out the steps for a sync task. Claude Code registers them as slash commands. Another agent can read the same file and follow it.
- **Reading discipline is part of the contract.** Lecture files put the summary on top and the full transcript below a `## Transcript` heading. Agents read down to that heading and stop unless the question needs the actual words, because a semester of transcripts will not fit in a context window.
- **The repo is text. The files are in the workdir.** Slides, PDFs, and your own homework live in each class's `workdir` (set in `class.md`), not in git. Each workdir keeps a synced copy of this rulebook as `_course-brain-rules.md`, so an agent session opened in the coursework folder knows the same rules and knows to come back here for tooling.
- **Anything ambiguous goes to `inbox/blackboard-review.md`.** Each entry states the decision in its heading and puts the evidence and the options in the body, so you can settle it from a phone.

## Example workflows

Five things I actually do. Longer versions, with the exact files read and written, are in [docs/WORKFLOWS.md](docs/WORKFLOWS.md).

| Ask | The agent reads | The agent writes |
|---|---|---|
| "Help me start HW3 for CS-2123." | the assignment spec, the lectures whose `topics` match, the slides in that module's `harvey/` folder | nothing in the repo; drafts and files go to the workdir's `homework/<assignment>/` |
| "Make me a study guide for the midterm from the last three weeks." | lecture summaries in the date window, transcripts only where a summary is thin, the exam file's spec | a study guide wherever you ask for it, usually the workdir's `exams/` |
| "I missed Tuesday, catch me up." | that date's lecture file, summary first, plus the previous lecture for continuity | nothing |
| "/digest" | every `class.md`, this week's lecture summaries, every open assignment's frontmatter | nothing; the digest goes to chat |
| "Process the blackboard review file." | `inbox/blackboard-review.md`, plus the assignment files each entry names | the `due:` lines you approve, the entries deleted once handled, then a commit |

## What runs on its own, and what never does

On its own, on a schedule:

- files new lectures from your recordings, one markdown file per class meeting
- files new graded items from Blackboard as assignment files
- rewrites a filed `due:` when Blackboard itself shows a different date, since Blackboard is the authority on its own deadlines
- mirrors course files, Ultra page text, and assignment spec text into each class's workdir
- creates and refreshes tasks in your task manager, closes finished ones, and marks files submitted when you check a task off
- commits, pushes if a remote exists, and regenerates its own schedule from your class times

Never, by design:

- change a due date because someone said a date out loud in a lecture
- create a task from a lecture transcript, since transcribed speech is too noisy to write to your todo list unreviewed
- submit anything, accept a course agreement, or click a submission button on Blackboard
- post, email, or reply anywhere as you
- overwrite an assignment body you edited when Blackboard's spec text changes underneath it
- guess when two things could match

Everything in that second list that still needs a decision goes to `inbox/blackboard-review.md` and, if you configured ntfy, to your phone. The flags stay there until you handle them.

## What it looks like on disk

The repo is the product. Markdown files, no app, no database. A real semester looks like this:

```
classes/
  cs-2123/                        # one folder per class, lowercase course code
    class.md                      # schedule, Harvey url, workdir, Granola folder
    syllabus.md
    lectures/
      2026-08-24.md               # summary up top, full transcript below
      2026-08-26.md
    assignments/
      hw1-linked-lists.md         # spec, due date, status, task id
      exam-1.md                   # calendar: true, so it lands on your calendar
    .bb-manifest.json             # what the last scan saw
    .bb-mirror.json               # what the mirror has downloaded
  math-2014/
    ...
examples/
  cs-2123/                        # synthetic class, copy into classes/ to try things
inbox/
  blackboard-review.md            # decisions waiting on you, never auto-applied
scripts/                          # blackboard login/scan/mirror, task sync, scheduler, linter, tests
docs/                             # vision, runbook, adding a class, adapting, workflows
.claude/skills/                   # /add-class /lecture-sync /blackboard-sync /assignment-sync /digest
CLAUDE.md                         # the rulebook; AGENTS.md is a symlink to it
```

Slides, PDFs, and your own homework are not in here. They live in each class's workdir, a cloud-synced `Coursework/<semester>/<class>/` folder with `harvey/` (script-owned mirror), `homework/`, `exams/`, `projects/`, and `materials/` inside it. Git gives you history and free sync of the text across machines.

## The stack I built it on

This works out of the box with my tools. Every one of them has alternatives, and swapping one is the point of a markdown-and-scripts design. [docs/ADAPTING.md](docs/ADAPTING.md) has the seams.

| Piece | I use | Why | Swap for |
|---|---|---|---|
| Agent | [Claude Code](https://claude.com/product/claude-code) | skills, MCP, runs headless on a schedule | Codex, Hermes, any agent CLI |
| Lecture capture | [Granola](https://granola.ai) (paid seat) | transcribes in-person audio, has an MCP | Whisper or any transcript source, via `scripts/lecture-import.py` |
| Tasks | [Todoist](https://todoist.com) | good API, syncs to my calendar | Reminders, TickTick, Notion, a markdown file |
| Credentials | [1Password](https://1password.com) | CLI plus service accounts for unattended login | Bitwarden CLI, `pass`, env vars |
| Phone pings | [ntfy](https://ntfy.sh) | free, no signup, one `curl` | Pushover, a Telegram bot, nothing |
| Scheduling | launchd (macOS built-in) | it's what my Mac speaks | cron, systemd timers, Task Scheduler |

Same tools as me? Clone, configure, done. Different tools? Most stages read a command from an environment variable, so the swap is usually one line in `~/.course-brain/env`. For the ones that need real work, the docs are written so an agent can do it. Open the repo and say "I use Bitwarden and TickTick instead of 1Password and Todoist, read docs/ADAPTING.md and rewire this," and you're maybe an hour from a working setup.

## Getting started

1. **Fork it, and make your copy private.** You'll be committing your own class content.
2. **Look at the example.** `cp -r examples/cs-2123 classes/cs-2123` gives you a synthetic class with two lectures and two assignments, so you can try `/digest` and `python3 scripts/check.py` before wiring anything up. `rm -rf classes/cs-2123` when you're done with it.
3. **Add a real class.** Open the repo in your agent and say "add my class". The `/add-class` skill collects the code, schedule, Blackboard url, and workdir, and scaffolds the folder. One run per course. Full process, including the steps you have to do yourself, in [docs/ADDING-A-CLASS.md](docs/ADDING-A-CLASS.md).
4. **Wire up what you use.** Granola needs a folder per class and a one-time MCP auth. Todoist needs an API token in `~/.config/todoist/token` or `TODOIST_API_TOKEN`. Blackboard needs your school login in a 1Password item and one `scripts/bb login`. Every step is optional and the repo degrades to whatever you connected.
5. **Set your overrides, if you need any.** `~/.course-brain/env` holds `export KEY=value` lines that the scheduled jobs source at startup. That's where `CB_MIRROR_DIRNAME`, `CB_TZ`, and the `CB_*_CMD` stage overrides go, along with tokens that launchd won't inherit from your shell.
6. **Schedule it** (optional, macOS). `python3 scripts/gen-schedule.py` installs two launchd jobs, one that syncs lectures and scans Blackboard after each class, and one that polls Blackboard every 30 minutes during the day. Preview with `--dry-run`, skip the poll with `--no-poll`. A laptop that sleeps is fine, since every run re-scans and a missed run costs nothing.
7. **Check your work.** `python3 scripts/check.py` lints every class, lecture, and assignment file. `python3 -m unittest discover -s scripts -p 'test_*.py'` runs the tests.

Then hit record when class starts, and ask your agent for help like it's a classmate who never misses a lecture.

More detail in [docs/OPERATIONS.md](docs/OPERATIONS.md) (the runbook), [docs/VISION.md](docs/VISION.md) (the design and why it's markdown-first), [docs/WORKFLOWS.md](docs/WORKFLOWS.md) (how agents actually use it), and [docs/ADAPTING.md](docs/ADAPTING.md) (making it yours).

## How I actually run it (optional extra credit)

The template assumes one machine and that's genuinely fine. My own setup adds one trick. The scheduled jobs live on an always-on Mac instead of my laptop, and [Tailscale](https://tailscale.com) puts my laptop, my phone, and that machine on one private network no matter whose wifi I'm on. That machine syncs lectures, scans Blackboard all day, and pushes to git. My laptop just pulls. When something needs a decision, my phone gets the ntfy ping, I tap it, and I handle it from claude.ai/code in bed. None of that changes the repo. It's the same scripts on a machine that never sleeps, and [docs/ADAPTING.md](docs/ADAPTING.md) covers the setup.

## Ground rules

- **Recording lectures.** Ask your professor first. Policies differ by instructor and course, and one ask on day one covers the semester. Remember that a transcript captures your classmates and your professor, not just the lecture, so treat the repo as their data too.
- **Academic integrity.** This gets your real course context in front of an AI so it can teach and organize. What you submit is governed by your professor's AI policy and TU's academic integrity policy. Know them, follow them.
- **Your data.** Keep your copy private. It holds your schedule, your professors' words, and your coursework. The scripts keep credentials in your password manager and session state outside the repo. Don't undo that.
- **The committed manifests hold Blackboard detail.** `.bb-manifest.json` and `.bb-mirror.json` are committed on purpose, because they're what makes a rerun idempotent. They carry gradebook column names, your course ids, and the internal file urls for everything posted. That's fine in a private repo and one more reason not to make yours public.

## Contributing

If you're a TU student using this, I'd love issues and PRs, especially fixes to the Harvey API map when Blackboard shifts under us, and adapters for other tool stacks. If you take it to another school, Blackboard is Blackboard everywhere. Change `CB_BB_BASE` and most of it should travel. Tell me how it goes.
