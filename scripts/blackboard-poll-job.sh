#!/bin/zsh
# optional launchd payload, every 30 min (see gen-schedule.py). pulls, then runs
# the same blackboard tail the lecture job runs — so a gradebook column posted
# during class reaches the repo within half an hour instead of at the next class.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="/tmp/course-brain-poll.lock"
SYNC_LOCK="/tmp/course-brain-sync.lock"
LOG_DIR="$HOME/Library/Logs/course-brain"

# optional per-machine env for unattended runs (e.g. OP_SERVICE_ACCOUNT_TOKEN,
# TODOIST_API_TOKEN) — launchd jobs don't inherit your shell environment
[ -f "$HOME/.course-brain/env" ] && source "$HOME/.course-brain/env"

# waking hours only. nothing gets posted at 4am, and a relogin at 4am would
# just burn a browser launch nobody sees
case "$(date '+%H')" in
  0[0-6]|23) exit 0 ;;
esac

mkdir -p "$LOG_DIR"
exec >> "$LOG_DIR/blackboard-poll.log" 2>&1
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

# the lecture job does everything this one does and more; don't queue behind it
syncpid=$(cat "$SYNC_LOCK/pid" 2>/dev/null || echo "")
if [ -n "$syncpid" ] && kill -0 "$syncpid" 2>/dev/null; then
  echo "deferring to lecture-sync (pid $syncpid)"
  exit 0
fi

cd "$REPO"
if git remote get-url origin >/dev/null 2>&1; then
  if ! git pull --rebase --autostash --quiet; then
    git rebase --abort 2>/dev/null || true
    echo "pull failed (conflict?); rebase aborted, retrying next run"
    exit 1
  fi
fi

# stage only what this job produces; lectures and hand edits wait for the lecture job
rc=0
CB_STAGE=scan CB_DRY="${CB_DRY:-0}" CB_LOG="$LOG_DIR/blackboard-poll.log" \
  "$REPO/scripts/blackboard-job.sh" || { rc=$?; echo "blackboard job failed (exit $rc)"; }

echo "--- done $(date '+%F %T') ---"
exit $rc
