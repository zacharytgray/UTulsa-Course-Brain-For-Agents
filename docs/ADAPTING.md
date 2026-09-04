# Adapting this to your tools

This repo works out of the box with one stack. Claude Code, Granola, Todoist, 1Password, ntfy, macOS launchd, and TU's Harvey. None of that is load-bearing to the design. The design is markdown files with frontmatter, small scripts, and skill files that tell an agent what to do, and every integration sits at the edge of it.

The fastest way to adapt it is to open the repo in your agent and describe your stack.

> "I use Bitwarden instead of 1Password and TickTick instead of Todoist. Read docs/ADAPTING.md and rewire the repo for my tools."

Each section below tells that agent, or you, exactly what to touch.

## What is and isn't pluggable

Be clear-eyed about this. There is no plugin system here, no adapter interface, no registry. What exists is two weaker but more honest things.

The first is **file-format contracts**. Every stage reads and writes plain markdown with frontmatter, and nothing downstream knows or cares which tool produced it. A lecture file is a lecture file whether Granola or Whisper made it. An assignment file is an assignment file whether Blackboard's scan or your own hand wrote it. So any replacement that emits the same shape drops in with zero changes elsewhere.

The second is **command-line seams**. The scheduled job runs each stage by `eval`ing a command string it reads from an environment variable, and the literal value `none` skips the stage. So swapping the lecture step, the LMS scan, the mirror, the task sync, or the notifier is one line in `~/.course-brain/env`, as long as your replacement command produces the right files.

What is genuinely not pluggable is the LMS itself. `blackboard-scan.py` and `blackboard-mirror.py` are written against Blackboard Ultra's JSON API and Microsoft Entra SSO, and there is no abstraction under them. Moving to Canvas or Moodle means writing new scripts that produce the same files, not implementing an interface. That is real work, and the sections below say how much.

## Integration points

`~/.course-brain/env` is where overrides go, one `export KEY=value` per line, mode 600. The job scripts source it at startup, which matters because launchd jobs don't inherit your shell environment. You can also just export them in your shell for a manual run.

| Stage | Scripts | Contract it has to satisfy | Override |
|---|---|---|---|
| Lecture capture | `.claude/skills/lecture-sync/SKILL.md`, `scripts/lecture-import.py` | writes `classes/<class>/lectures/YYYY-MM-DD.md` with frontmatter, a summary, and a `## Transcript` heading | `CB_LECTURE_SYNC_CMD` (default: headless `claude -p "/lecture-sync"`) |
| LMS discovery | `scripts/blackboard-scan.py` | writes assignment files, flags to `inbox/blackboard-review.md`, state to `classes/<class>/.bb-manifest.json` | `CB_LMS_SCAN_CMD` (default: `python3 scripts/blackboard-scan.py --skip-todoist`) |
| Course file mirror | `scripts/blackboard-mirror.py` | fills the workdir mirror folder, fills assignment spec text, state in `classes/<class>/.bb-mirror.json` | `CB_LMS_MIRROR_CMD` (default: `python3 scripts/blackboard-mirror.py`), `CB_MIRROR_DIRNAME` for the folder name |
| Task manager | `scripts/todoist-sync.py`, `.claude/skills/assignment-sync/SKILL.md` | reads `title`, `due`, `status`, `calendar`; owns one id line in frontmatter | `CB_TASK_SYNC_CMD` (default: `python3 scripts/todoist-sync.py`) |
| Notification | `scripts/blackboard-job.sh` | sends a string somewhere you'll see it | `CB_NOTIFY_CMD` (default: the ntfy curl) |
| Login and credentials | `scripts/blackboard.py` | hands the client a username, a password, and a current TOTP code | none; edit three functions |
| Scheduling | `scripts/gen-schedule.py` | runs `scripts/lecture-sync-job.sh` after each class and `scripts/blackboard-poll-job.sh` every 30 min | none; launchd only, `entries()` is the reusable part |

Setting any of the five command overrides to the literal string `none` skips that stage. `CB_NOTIFY_CMD=none` disables pings entirely.

Other environment variables the scripts read:

| Variable | Default | Read by | Meaning |
|---|---|---|---|
| `CB_MIRROR_DIRNAME` | `harvey` | `blackboard-mirror.py`, and the scan's diff label | name of the script-owned mirror folder inside each workdir |
| `CB_TZ` | `America/Chicago` | `blackboard-scan.py`, `todoist-sync.py` | timezone Blackboard's UTC due dates convert into |
| `CB_BB_BASE` | `https://harvey.utulsa.edu` | `blackboard.py`, `blackboard-mirror.py` | your school's Blackboard domain |
| `CB_BB_STATE` | `~/.course-brain/bb-state.json` | `blackboard.py` | where the session cookies are saved |
| `CB_OP_ITEM` / `CB_OP_VAULT` | `Utulsa` / your default vault | `blackboard.py` | which 1Password item holds the school login |
| `TODOIST_API_TOKEN` | falls back to `~/.config/todoist/token` | `todoist-sync.py` | task manager credential |
| `CLAUDE_BIN` | whatever `claude` resolves to on `PATH` | `lecture-sync-job.sh` | agent binary, when it isn't on the job's `PATH` |
| `CB_DEBUG` | unset | `blackboard.py` | verbose login tracing, plus `~/.course-brain/login-fail.png` |
| `CB_DRY` | `0` | `blackboard-job.sh` | scan and mirror, then stop before task sync, commit, push, and pings |
| `CB_FORCE_MIRROR` | `0` | `blackboard-job.sh` | mirror even when nothing changed |
| `CB_STAGE` | `all` | `blackboard-job.sh` | `all` stages everything, `scan` stages only scan and task outputs |
| `CB_LOG` | the lecture-sync log | `blackboard-job.sh` | log path named in the failure ping |
| `COURSE_BRAIN_FROM_JOB` | unset | `gen-schedule.py` | set by the job so a schedule regeneration knows it's automated |

## Swap the task manager (Todoist to anything)

The contract is narrow. Your replacement reads every `classes/*/assignments/*.md`, uses the frontmatter fields `title`, `due`, `status`, and `calendar`, and owns exactly one id line in that frontmatter. Ours is `todoist_task_id`; call yours `ticktick_task_id` if you like, since `check.py` doesn't validate the name. Nothing else in the repo reads the id.

Five behaviors make up the whole integration, and `scripts/todoist-sync.py` is the reference for all five:

1. create a task for any assignment file with a `due` and no id, then write the new id back into the file
2. refresh the title, description, and due date from the file on every run, so the file stays the only place a deadline can move
3. close the task when the file's `status` is `submitted` or `graded`
4. flip the file to `status: submitted` and append a `## Submitted` section when the task gets checked off
5. read task comments and append unseen ones to the file under `## Notes`, never writing or deleting comments

Then point `CB_TASK_SYNC_CMD` at your script and update `.claude/skills/assignment-sync/SKILL.md` so the agent-facing procedure names your tool.

No task app at all? Set `CB_TASK_SYNC_CMD=none` and ask `/digest` what's due. Every deadline is already in the files.

## Swap lecture capture (Granola to anything)

The pipeline needs one thing, a transcript and a summary per lecture, attributable to a class and readable by an agent. The file format is the contract:

```markdown
---
granola_id: <any stable per-recording id>   # or source_id, both work
class: CS-2123
date: 2026-09-04
title: Hash tables
topics: [hashing, collision resolution, load factor]
---

<summary>

## Transcript

<full transcript>
```

Everything downstream reads that format, not Granola. `check.py` wants exactly one of `granola_id` or `source_id`, and wants it to be unique across the repo. That's all the id is for, idempotency, so a sync can tell what it already filed.

Two paths off Granola:

- **Keep it scripted.** Run your own transcription however you like, then `python3 scripts/lecture-import.py cs-2123 lecture.txt --date 2026-09-04 --title "Hash tables" --summary summary.md --id whisper-2026-09-04`. It writes the file, handles the `-2` suffix for a second meeting on the same day, and records `source_id`. Wrap your transcription plus that call in a shell script and point `CB_LECTURE_SYNC_CMD` at it.
- **Keep it agentic.** Rewrite `.claude/skills/lecture-sync/SKILL.md` against your source, another notetaker's MCP or a folder of recordings, and leave `CB_LECTURE_SYNC_CMD` alone.

One thing you lose by leaving the skill. Deadline-conflict flagging, where a date spoken in lecture that contradicts a filed `due:` becomes an entry in `inbox/blackboard-review.md`, lives in the lecture-sync skill, not in any script. `lecture-import.py` files the transcript and stops. If you want that behavior on a non-Granola path, either port that section of the skill into your own flow or ask your agent to review new lecture files for deadline mentions after each import.

`classes/*/class.md` has a `granola_folder_id` field. Repurpose it as your own source id or ignore it. An empty value is a lint warning, not an error.

## Another school, or another LMS

Three scripts make up the Blackboard integration, and they're tied to Blackboard Ultra's JSON API and Microsoft Entra SSO:

- `scripts/blackboard.py` is the login and the API client. Playwright drives the SSO flow, credentials come from a password manager, and the session lands in `~/.course-brain/bb-state.json`. `scripts/bb` is the CLI wrapper.
- `scripts/blackboard-scan.py` is discovery and diff. It reads the gradebook columns and the content tree, files new graded items as assignment files, corrects due dates that moved, flags anything ambiguous to `inbox/blackboard-review.md`, and records what it saw in `classes/<class>/.bb-manifest.json`.
- `scripts/blackboard-mirror.py` is the file mirror. It walks the content tree, downloads everything into the class workdir under the mirror folder, renders Ultra pages to markdown, fills assignment spec text into the repo, and tracks all of it in `classes/<class>/.bb-mirror.json`.

**Another Blackboard school.** Set `CB_BB_BASE` to your domain and the endpoints in the [blackboard-sync skill](../.claude/skills/blackboard-sync/SKILL.md) should mostly hold. The SSO screens in `blackboard.py` are written for Microsoft Entra, which is common but not universal. Run `scripts/bb login --headed` once and watch where it gets stuck.

**Canvas, Moodle, or Brightspace.** There is no LMS abstraction to implement, so this is a rewrite of the scan and the mirror against your LMS's API, and those APIs are friendlier than Blackboard's. Aim at the same outputs, assignment files plus review flags plus a manifest for the scan, and a workdir mirror plus spec text plus a mirror state file for the mirror. Then point `CB_LMS_SCAN_CMD` and `CB_LMS_MIRROR_CMD` at your scripts. Everything else carries over unchanged, the job script, the skills, the task sync, the linter, and the repo layout.

**Renaming the mirror folder.** "Harvey" is TU's name for its Blackboard install. `CB_MIRROR_DIRNAME=blackboard` changes the folder name inside every workdir and the diff label the scan uses in review flags. Three places still say Harvey in prose, and you can leave them or edit them. They are `CLAUDE.md`, the blackboard-sync skill, and the `Full spec on Harvey (not yet mirrored).` placeholder string that the scan writes and the mirror looks for. That placeholder is a matched pair across two scripts, so if you change it, change both.

## Swap the password manager (1Password to anything)

`scripts/blackboard.py` needs three strings at login time. Username, password, and a current TOTP code. The 1Password specifics live in three small functions, `op_env()`, `op()` with `creds()`, and `totp()`. Replace their bodies with calls to `bw`, `pass`, `rbw`, or your manager's CLI, and keep the property that matters. Credentials go from the manager straight into the script, and the agent never sees or types them.

## Swap the notifier (ntfy to anything)

Set `CB_NOTIFY_CMD` to any command that can send a string. The job runs it with the notification title in the environment variable `CB_NOTIFY_TITLE` and the body on stdin, so a wrapper is usually two lines:

```sh
export CB_NOTIFY_CMD='xargs -0 -I{} curl -s -F "token=$PUSHOVER_TOKEN" -F "user=$PUSHOVER_USER" -F "title=$CB_NOTIFY_TITLE" -F "message={}" https://api.pushover.net/1/messages.json'
```

`CB_NOTIFY_CMD=none` turns pings off. Without a notifier the flags still accumulate in `inbox/blackboard-review.md` and `/digest` still surfaces them. You just have to go look.

## Swap the agent (Claude Code to Codex, Hermes, anything)

- Skills in `.claude/skills/` are plain markdown procedures. Any agent that can read a file can follow one. Wire them into your agent's own mechanism, or just tell it to read the SKILL.md and follow it.
- `AGENTS.md` is a symlink to `CLAUDE.md`, so agents that look for either name get the same project context with no second copy to maintain.
- The scheduled job invokes the agent through `CB_LECTURE_SYNC_CMD`, or through `CLAUDE_BIN` if you're keeping the default Claude Code invocation and it just isn't on the job's `PATH`.
- The Python scripts don't know or care what agent you use.

## Not on macOS

Two things are Mac-specific.

**Scheduling.** `scripts/gen-schedule.py` writes launchd plists, and launchd is the only scheduler it knows. The reusable part is `entries()`, which parses the `schedule:` line out of every `class.md`, skips classes past their `ends` date, and returns the run times, each one a class's end time plus 30 minutes. Only `main()` writes plists. On Linux, generate cron lines or a systemd timer from `entries()`; on Windows, `schtasks`. Whatever you generate should run `scripts/lecture-sync-job.sh` at those times and `scripts/blackboard-poll-job.sh` every 30 minutes.

**Granola** is a desktop app for macOS and Windows, so check your platform, or take the `lecture-import.py` path above.

Log paths (`~/Library/Logs/course-brain/`) are cosmetic. Change them in `lecture-sync-job.sh`, `blackboard-poll-job.sh`, and `gen-schedule.py`.

## Running the sync on a separate always-on machine

The template assumes one machine and that's fine. The job runs when your laptop is awake and catches up when it isn't, since every run re-scans and idempotency means a missed run costs nothing.

If you want true hands-free sync, put the scheduled job on any always-on machine.

1. Give that machine its own clone, its own logged-in agent CLI, its own lecture-source auth, its own Blackboard session, and its own task-manager token. The "Setting up from scratch" list in [OPERATIONS.md](OPERATIONS.md) is that checklist.
2. Add a private git remote and let the job push, which it already does when a remote exists. Your other machines just pull.
3. Put the two machines on one private network so you can reach the sync machine from campus wifi to read logs or fix a login. [Tailscale](https://tailscale.com) is what I use for that.

Unattended runs are where a 1Password **service account** matters, since the desktop-app integration only works with you at the keyboard. See [OPERATIONS.md](OPERATIONS.md) for that setup.

## Odds and ends

`scripts/nb-text.py` dumps the visible text of a Mathematica notebook (`.nb`) with no kernel, one line per leaf cell. It's here because some math courses hand out notebooks. If yours don't, delete it. Nothing else in the repo calls it.

After any swap, run the checks:

```bash
python3 scripts/check.py
python3 -m unittest discover -s scripts -p 'test_*.py'
```
