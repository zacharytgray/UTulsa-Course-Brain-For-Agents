# Adapting this to your tools

This repo works out of the box with a specific stack: Claude Code, Granola, Todoist, 1Password, ntfy, macOS launchd, and TU's Harvey. None of those are load-bearing to the *design* — the design is markdown files with frontmatter, small scripts, and skill files that tell an agent what to do. Every integration is a thin, replaceable edge.

The fastest way to adapt it: open the repo in your agent and describe your stack. For example:

> "I use Bitwarden instead of 1Password and TickTick instead of Todoist. Read docs/ADAPTING.md and rewire the repo for my tools."

Each section below tells that agent (or you) exactly what to touch.

## Swap the task manager (Todoist → anything)

Touch points:

- `scripts/todoist-sync.py` — the whole integration. It reads `classes/*/assignments/*.md`, creates a task per file, refreshes descriptions/due dates, closes finished ones, and mirrors task comments into the file. Port those five behaviors to your API and you're done. The contract with the rest of the repo is just the frontmatter: it reads `title`, `due`, `status`, `calendar`, and it owns the `todoist_task_id` line (rename the field if you like — `check.py` doesn't validate it).
- `.claude/skills/assignment-sync/SKILL.md` — the agent-facing procedure; update the tool name and rules.
- No task app at all? Delete both and ask `/digest` what's due — the files already hold every deadline.

## Swap lecture capture (Granola → anything)

The pipeline only needs: *a transcript and a summary per lecture, attributable to a class, fetchable by an agent.*

- Keep the lecture file format (`lectures/YYYY-MM-DD.md`, frontmatter + summary + `## Transcript`). Everything downstream (digest, homework help, deadline flagging) reads that format, not Granola.
- Rewrite `.claude/skills/lecture-sync/SKILL.md` for your source: an MCP for another notetaker, a Whisper transcription of a phone recording dropped in `inbox/`, whatever. Swap `granola_id` for any stable per-recording id — it's only used for idempotency (`check.py` checks presence and uniqueness).
- `classes/*/class.md` has a `granola_folder_id` field; repurpose or ignore it.

## Swap the password manager (1Password → anything)

`scripts/blackboard.py` needs three strings at login time: username, password, and a current TOTP code. The 1Password specifics live in three tiny functions — `op_env()`, `op()`/`creds()`, and `totp()`. Replace their bodies with calls to `bw`, `pass`, `rbw`, or your manager's CLI. Keep the property that credentials go from the manager straight into the script — the agent should never see or type them.

## Swap the notifier (ntfy → anything)

The ping is one `curl` block at the bottom of `scripts/lecture-sync-job.sh`. Replace it with Pushover, a Telegram bot, an email — anything that can send a string from a shell script. Or delete the block; flags still accumulate in `inbox/blackboard-review.md` and `/digest` surfaces them.

## Swap the agent (Claude Code → Codex, etc.)

- The skills in `.claude/skills/` are plain markdown procedures — any agent that can read files can follow them; wire them into your agent's equivalent mechanism (Codex custom prompts, etc.).
- The scheduled job shells out to `claude -p "/lecture-sync"` in `scripts/lecture-sync-job.sh`; swap in your agent's headless invocation.
- The Python scripts don't care what agent you use.

## Another school / another LMS

Blackboard Ultra is Blackboard Ultra everywhere: set `CB_BB_BASE` to your school's domain and the API endpoints in the [blackboard-sync skill](../.claude/skills/blackboard-sync/SKILL.md) should mostly hold. The SSO screens in `blackboard.py` are written for Microsoft Entra (very common) — run `scripts/bb login --headed` once and watch where it gets stuck. Canvas/Moodle/Brightspace: the scan script needs a rewrite against their (friendlier) APIs, but the repo layout, skills, and Todoist sync carry over unchanged.

## Not on macOS

Two things are Mac-specific:

- **Scheduling.** `scripts/gen-schedule.py` writes a launchd plist. On Linux, generate cron lines or a systemd timer instead — the interesting logic (parsing `schedule:` from every class.md and computing end-time + 30 min) is already isolated in that script's `entries()`; only `main()` writes the plist. On Windows, Task Scheduler via `schtasks`.
- **Granola** is a desktop app (macOS/Windows); check your platform.

Log paths (`~/Library/Logs/course-brain/`) are cosmetic — change them in `lecture-sync-job.sh` and `gen-schedule.py`.

## Running the sync on a separate always-on machine

The template assumes one machine, and that's fine — the job just runs when your laptop is awake, and catches up when it isn't (every run re-scans; idempotency means missed runs cost nothing).

If you want true hands-free sync, put the scheduled job on any always-on machine instead:

1. Give that machine its own clone, logged-in Claude CLI, Granola MCP auth, Blackboard session, and Todoist token (the "Setting up from scratch" list in [OPERATIONS.md](OPERATIONS.md)).
2. Add a **private git remote** to the repo and let the job push (it already does when a remote exists). Your other machines just `git pull`.
3. The trick that makes this painless is [Tailscale](https://tailscale.com): every device on one private network no matter where you are, so you can ssh into the sync machine from campus wifi to check logs or fix a login. That's how I run mine — the sync lives on an always-on machine at home, my laptop pulls, and my phone gets the ntfy pings.

Unattended runs are where the 1Password **service account** matters (see [OPERATIONS.md](OPERATIONS.md)) — the desktop-app integration only works with you at the keyboard.
