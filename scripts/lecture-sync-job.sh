#!/bin/zsh
# scheduled sync payload (launchd runs this — see gen-schedule.py). pulls if a
# remote exists, runs /lecture-sync headless, scans blackboard, refreshes the
# content mirror, syncs todoist, commits, pushes, optionally pings your phone,
# then regenerates the schedule from class.md so it stays current.
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

# a poll run may be mid-flight; give it up to 5 min to finish before we pull
POLLLOCK="/tmp/course-brain-poll.lock"
waited=0
while pollpid=$(cat "$POLLLOCK/pid" 2>/dev/null) && [ -n "$pollpid" ] && kill -0 "$pollpid" 2>/dev/null; do
  if [ "$waited" -ge 300 ]; then
    echo "poll job still running (pid $pollpid) after 5 min, proceeding"
    break
  fi
  sleep 10
  waited=$((waited + 10))
done

cd "$REPO"
if git remote get-url origin >/dev/null 2>&1; then
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

# headless runs never retry a server cached as needs-auth, so one transient 401
# poisons every later run (the token refresh actually works fine headless).
# scrub granola from the cache so each run gets a real connection attempt.
/usr/bin/python3 - <<'PY' || true
import json, os
p = os.path.expanduser("~/.claude/mcp-needs-auth-cache.json")
if os.path.exists(p):
    d = json.load(open(p))
    if d.pop("granola", None) is not None:
        json.dump(d, open(p, "w"))
        print("scrubbed stale granola needs-auth cache entry")
PY

# allow the claude.ai Granola connector too — it's the fallback the model
# reaches for when the local granola server is unavailable
"$CLAUDE" -p "/lecture-sync" \
  --model opus \
  --permission-mode acceptEdits \
  --allowedTools "mcp__granola,mcp__claude_ai_Granola,Bash(git pull:*)" &
claude_pid=$!
( sleep "$SYNC_TIMEOUT"; kill "$claude_pid" 2>/dev/null ) &
watchdog=$!
sync_ok=1
wait "$claude_pid" || { sync_ok=0; echo "claude run failed or timed out"; }
kill "$watchdog" 2>/dev/null || true

# scan, mirror, rulebook copy, todoist, commit, push, schedule, ping — shared
# with the optional poll job. worth running even if the lecture run died; it's a
# separate source. forced mirror: the class that just ended is the one with new
# material
stage=all
[ "$sync_ok" = 1 ] || stage=scan
CB_STAGE="$stage" CB_FORCE_MIRROR=1 CB_LOG="$LOG_DIR/lecture-sync.log" \
  "$REPO/scripts/blackboard-job.sh"
