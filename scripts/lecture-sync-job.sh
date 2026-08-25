#!/bin/zsh
# scheduled sync payload (launchd runs this — see gen-schedule.py). pulls if a
# remote exists, runs /lecture-sync headless, scans blackboard, syncs todoist,
# commits, pushes, optionally pings your phone, then regenerates the schedule
# from class.md so it stays current.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"
LOCK="/tmp/course-brain-sync.lock"
LOG_DIR="$HOME/Library/Logs/course-brain"
SYNC_TIMEOUT=2400  # seconds before we give up on the headless run

# optional per-machine env for unattended runs (e.g. OP_SERVICE_ACCOUNT_TOKEN,
# TODOIST_API_TOKEN) — launchd jobs don't inherit your shell environment
[ -f "$HOME/.course-brain/env" ] && source "$HOME/.course-brain/env"

mkdir -p "$LOG_DIR"
exec >> "$LOG_DIR/lecture-sync.log" 2>&1
echo "=== run $(date '+%F %T') ==="

# don't overlap runs; recover from locks left by a crashed or killed run
if ! mkdir "$LOCK" 2>/dev/null; then
  oldpid=$(cat "$LOCK/pid" 2>/dev/null || echo "")
  if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
    echo "already running (pid $oldpid), skipping"
    exit 0
  fi
  echo "stale lock (pid ${oldpid:-unknown} gone), taking over"
  rm -rf "$LOCK"
  mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

cd "$REPO"
has_remote=0
if git remote get-url origin >/dev/null 2>&1; then
  has_remote=1
  # autostash: a failed claude run can leave dirty files (they commit next
  # successful run); without it every later pull would die on the dirty tree.
  # on a rebase conflict (flags got processed elsewhere while a run was
  # mid-flight), abort so the repo isn't left wedged mid-rebase for every run
  if ! git pull --rebase --autostash --quiet; then
    git rebase --abort 2>/dev/null || true
    echo "pull failed (conflict?); rebase aborted, retrying next run"
    exit 1
  fi
fi

"$CLAUDE" -p "/lecture-sync" \
  --model opus \
  --permission-mode acceptEdits \
  --allowedTools "mcp__granola" &
claude_pid=$!
( sleep "$SYNC_TIMEOUT"; kill "$claude_pid" 2>/dev/null ) &
watchdog=$!
sync_ok=1
wait "$claude_pid" || { sync_ok=0; echo "claude run failed or timed out"; }
kill "$watchdog" 2>/dev/null || true

# worth running even if the lecture run died; it's a separate source
/usr/bin/python3 scripts/blackboard-scan.py --skip-todoist || echo "blackboard scan failed"

# after the scan so new assignment files get tasks in the same run
/usr/bin/python3 scripts/todoist-sync.py || echo "todoist sync failed"

if [ "$sync_ok" = 1 ]; then
  git add -A
else
  # a failed claude run can leave half-written lecture files; stage only the
  # scan and todoist outputs, lectures stay uncommitted until the next good run
  # (per-spec, guarded: git add fatals on any pathspec matching nothing)
  for spec in 'classes/*/assignments/*' 'classes/*/.bb-manifest.json' inbox; do
    git add -A -- "$spec" 2>/dev/null || true
  done
fi
if [ -n "$(git diff --cached --name-only)" ]; then
  git commit -m "sync: automated run $(date '+%F %H:%M')" --quiet
  echo "committed $(git diff-tree --no-commit-id --name-only -r HEAD | wc -l | tr -d ' ') file(s)"
fi
# push whenever local is ahead, not just when this run committed — a failed
# push would otherwise strand commits until the next run with new content
pushed=0
if [ "$has_remote" = 1 ]; then
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse '@{u}')" ]; then
    if git push --quiet; then
      pushed=1
      echo "pushed"
    else
      echo "push failed"
    fi
  else
    echo "nothing new"
  fi
else
  # no remote: the local repo is the only copy, treat every commit as "pushed"
  # so the phone ping below still fires
  pushed=1
  echo "no remote configured, skipping push"
fi

COURSE_BRAIN_FROM_JOB=1 /usr/bin/python3 scripts/gen-schedule.py

# optional phone ping via ntfy.sh — put your topic (one line, the topic name or
# a full url) in ~/.course-brain/ntfy-topic. decision-only: it fires just for
# review-file entries that haven't been pinged before, so routine syncs stay
# silent. state file = flag headings already pinged; each flag pings exactly
# once — removals never ping, and a flag filed on a run whose push failed
# still pings on the next successful one
PINGED="$HOME/.course-brain/pinged-flags"
if [ "$pushed" = 1 ] && [ -f inbox/blackboard-review.md ]; then
  touch "$PINGED"
  new_flags=$(grep '^## ' inbox/blackboard-review.md | grep -Fxv -f "$PINGED" || true)
  if [ -n "$new_flags" ]; then
    if [ -f "$HOME/.course-brain/ntfy-topic" ]; then
      topic=$(head -1 "$HOME/.course-brain/ntfy-topic")
      case "$topic" in
        http*) url="$topic" ;;
        *) url="https://ntfy.sh/$topic" ;;
      esac
      count=$(printf '%s\n' "$new_flags" | wc -l | tr -d ' ')
      body=$(printf '%s\n' "$new_flags" | head -12 | sed 's/^## //')
      if [ "$count" -gt 12 ]; then
        body="$body
+$((count - 12)) more"
      fi
      body="$body
Decide via claude.ai/code — \"process the blackboard review file\""
      if curl -fsS -H "Title: course-brain: decision needed" \
           -H "Click: https://claude.ai/code" -d "$body" "$url" >/dev/null; then
        printf '%s\n' "$new_flags" >> "$PINGED"
      else
        echo "ntfy ping failed"  # not recorded as pinged; retries next run
      fi
    else
      echo "ntfy topic not configured, skipping ping"
    fi
  else
    echo "no new review flags, no ping"
  fi
fi
