# UTulsa Course Brain (for agents)

**Your AI can't help you with school if it can't see your school.** This repo fixes that.

It's a template for a "course brain": one git repo that holds everything from your semester at TU — lecture transcripts, syllabi, assignment specs, due dates — structured so an AI agent (Claude Code, Codex, whatever you run) can use all of it. Point an agent at this repo and it already knows what your professor said on Tuesday, what HW3 actually asks for, and what's due this week. There's no longer a disconnect between what your AI sees and what shows up on [Harvey](https://harvey.utulsa.edu).

I built this for my own classes at TU and I'm sharing the cleaned-up template because I think every student here should have something like it. Reign 'Cane. 💙

## What it does

- **A local, always-current mirror of Harvey.** A scheduled scan reads Harvey's gradebook and content tree through its JSON API and files every assignment as a markdown file with the title, due date, points, and source link. When a professor moves a due date on Harvey, the file updates itself on the next run. The repo ships with a working Harvey API map (`.claude/skills/blackboard-sync/SKILL.md`) — endpoints, auth flow, and the gotchas, already figured out.
- **Agents can reach Harvey behind the scenes.** Login is scripted (Playwright + your password manager + TOTP), so an agent can check for new postings or pull an assignment spec without you touching a browser — and without the agent ever seeing your password.
- **Every lecture, remembered.** Hit record in [Granola](https://granola.ai) at the start of class. Thirty minutes after class ends, a scheduled job files the transcript and summary into the repo automatically. Studying with an agent means studying with the actual lectures, not a textbook's idea of them.
- **Deadlines flow to your todo app.** New assignment files become [Todoist](https://todoist.com) tasks automatically, with the full spec in the task description — so your phone always shows current specs and deadlines. Exams marked `calendar: true` land on your calendar too.
- **It listens for what Harvey doesn't say.** When a professor says "actually, push that to Friday" in lecture, the transcript pipeline notices the conflict with the filed due date and flags it for your decision — with an optional phone ping via [ntfy](https://ntfy.sh). Nothing changes without your ok.
- **Weekly digest.** `/digest` — what happened in each class this week, what's due, what needs a look.

## Talk to it like this

Open your agent in this repo and just ask:

> "Hey Claude, can you download my most recent homework assignment for my math class?"

> "Yo! I am so stuck on transposing matrices. Can you make a 3Blue1Brown-style animation to show me how it works?"

> "I'm feeling a bit overwhelmed. Can you help me get a sense of what's due the soonest and what would be the highest value thing to knock out tonight?"

The agent reads the assignment spec, the lectures it builds on, and your deadlines — then actually helps, with your real course context instead of guesses.

## What it looks like on disk

The repo *is* the product — markdown files, no app, no database. A real semester looks like:

```
classes/
  cs-2123/                        # one folder per class, lowercase course code
    class.md                      # schedule, Harvey url, Granola folder — the wiring
    syllabus.md
    lectures/
      2026-08-24.md               # summary up top, full transcript below
      2026-08-26.md
    assignments/
      hw1-linked-lists.md         # spec + due date + status, synced to Todoist
      hw2-bst.md
      exam-1.md                   # calendar: true → lands on your calendar
  math-2014/
    class.md
    syllabus.md
    lectures/ ...
    assignments/ ...
inbox/
  blackboard-review.md            # things that need YOUR decision (flagged, never auto-applied)
                                  # (binary files — slides, PDFs, your own homework — live outside
                                  #  the repo in each class's workdir; the repo stays text-only)
scripts/                          # Harvey login/scan, Todoist sync, scheduler, linter
docs/                             # design, runbook, how to add a class, how to adapt it
.claude/skills/                   # /add-class, /lecture-sync, /blackboard-sync, /assignment-sync, /digest
```

Every file has simple frontmatter an agent (or grep) can query. Git gives you history and free sync across machines.

## The stack I built it on

Full disclosure: this works out of the box with *my* tools. Each one has plenty of alternatives, and the whole point of a markdown-and-scripts design is that swapping one out is easy — see [docs/ADAPTING.md](docs/ADAPTING.md).

| Piece | I use | Why | Swap for |
|---|---|---|---|
| Agent | [Claude Code](https://claude.com/product/claude-code) | skills, MCP, runs headless on a schedule | Codex, or any agent CLI |
| Lecture capture | [Granola](https://granola.ai) (paid seat) | transcribes in-person audio, has an MCP | Whisper, otter.ai, any transcript source |
| Tasks | [Todoist](https://todoist.com) | good API, syncs to my calendar | Reminders, TickTick, Notion, a markdown file |
| Credentials | [1Password](https://1password.com) | CLI + service accounts for unattended login | Bitwarden CLI, `pass`, env vars |
| Phone pings | [ntfy](https://ntfy.sh) | free, no signup, one `curl` | Pushover, Telegram bot, nothing |
| Scheduling | launchd (macOS built-in) | it's what my Mac speaks | cron, systemd timers, Task Scheduler |

If you use the same tools I do: clone, configure, done. If you don't: the docs are written so an agent can do the swap for you. Open the repo, say "I use Bitwarden and TickTick instead of 1Password and Todoist — adapt this," and you're probably an hour away from a working setup. That's not a cop-out; it's the design. Everything is small scripts and markdown procedures an agent can read and rewrite.

## Getting started

1. **Clone this repo** (or fork it first — you'll be committing your own class content, so make your copy **private**).
2. Open it in Claude Code and say **"add my class"** — the `/add-class` skill walks you through one course: code, schedule, Harvey url. Repeat per class.
3. **Wire up what you use.** Granola: create a folder per class, one-time MCP auth. Todoist: drop your API token in `~/.config/todoist/token`. Harvey: put your TU login in a 1Password item and run `scripts/bb login` once. Each step is optional — the repo degrades gracefully to whatever you've connected.
4. **Schedule it** (optional, macOS): `python3 scripts/gen-schedule.py` installs two launchd jobs, one that syncs lectures and scans Harvey after each class, and one that polls Harvey every 30 minutes during the day (`--no-poll` skips that one). Runs fine on the laptop you already own; an always-on machine is nicer but not required.
5. Hit record in Granola when class starts, and ask your agent for help like it's a classmate who never misses a lecture.

Details: [docs/ADDING-A-CLASS.md](docs/ADDING-A-CLASS.md) for setup, [docs/OPERATIONS.md](docs/OPERATIONS.md) for the runbook, [docs/VISION.md](docs/VISION.md) for the design and why it's markdown-first, [docs/ADAPTING.md](docs/ADAPTING.md) for making it yours.

## How I actually run it (optional extra credit)

The template assumes everything runs on one machine, and that's genuinely fine. My own setup adds one trick: the scheduled jobs live on an always-on Mac mini, and [Tailscale](https://tailscale.com) keeps my laptop, phone, and that machine on one private network no matter whose wifi I'm on. The mini syncs lectures and scans Harvey all day and pushes to git; my laptop just pulls. When something needs a decision, my phone gets the ntfy ping, I tap it, and handle it from claude.ai/code in bed. None of that changes the repo — it's the same scripts on a machine that never sleeps. [docs/ADAPTING.md](docs/ADAPTING.md) covers it.

## Ground rules

- **Recording lectures:** ask your professor first. Policies differ by instructor and course — one ask on day one covers the semester.
- **Academic integrity:** this tool gets your real course context in front of an AI so it can *teach and organize*. What you submit is governed by your professor's AI policy and TU's academic integrity policy. Know them, follow them.
- **Your data:** keep your copy of this repo private. It will contain your schedule, your professors' words, and your coursework. The scripts keep credentials in your password manager and session state outside the repo — don't undo that.

## Contributing

If you're a TU student using this: I'd love issues and PRs, especially fixes to the Harvey API map when Blackboard shifts under us, and adapters for other tool stacks. If you take this to another school — Blackboard is Blackboard everywhere; change the base URL and most of it should travel. Tell me how it goes.
