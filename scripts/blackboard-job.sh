#!/bin/zsh
# the blackboard half of a sync run: scan, mirror, rulebook copy, todoist,
# commit, push, regenerate the schedule, ping. shared by the lecture-sync job
# (which runs it after its headless claude step) and the optional 30-min poll
# job. no lock of its own — the caller holds one.
#
# env in:
#   CB_STAGE=all|scan     all = git add -A; scan = only scan/todoist outputs
#   CB_FORCE_MIRROR=1     always mirror, instead of only when something changed
#   CB_DRY=1              scan + mirror + rulebook, then stop: no todoist, commit, push, schedule, pings
#   CB_LOG=<path>         log path named in the failure ping
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="${CB_STAGE:-all}"
DRY="${CB_DRY:-0}"
STATE="$HOME/.course-brain"
MIRROR_STAMP="$STATE/last-mirror"
FAILS="$STATE/scan-failures"
FAIL_PINGED="$STATE/scan-failure-pinged"
LOG="${CB_LOG:-$HOME/Library/Logs/course-brain/lecture-sync.log}"

mkdir -p "$STATE"
cd "$REPO"

ping_phone() {  # title, body — no-op when no topic is configured
  [ -f "$STATE/ntfy-topic" ] || { echo "ntfy topic not configured, skipping ping"; return 1; }
  local topic url
  topic=$(head -1 "$STATE/ntfy-topic")
  case "$topic" in
    http*) url="$topic" ;;
    *) url="https://ntfy.sh/$topic" ;;
  esac
  curl -fsS -H "Title: $1" -H "Click: https://claude.ai/code" -d "$2" "$url" >/dev/null \
    || { echo "ntfy ping failed"; return 1; }
}

# scan first: it's 2-3 requests per class and it's what catches a new gradebook
# column. consecutive failures mean the blackboard login is broken, so count them
if /usr/bin/python3 scripts/blackboard-scan.py --skip-todoist; then
  rm -f "$FAILS"
else
  echo "blackboard scan failed"
  fails=$(( $(cat "$FAILS" 2>/dev/null || echo 0) + 1 ))
  echo "$fails" > "$FAILS"
  # bends the decision-only ping rule on purpose: a silently broken login is
  # worse than one fyi. once per 24h, and only after it's clearly not transient
  if [ "$fails" -ge 3 ] && [ "$DRY" != 1 ] &&
     { [ ! -f "$FAIL_PINGED" ] || [ -n "$(find "$FAIL_PINGED" -mmin +1440 2>/dev/null)" ]; }; then
    if ping_phone "course-brain: blackboard scan failing" \
         "$fails runs in a row have failed the blackboard scan.
Log: $LOG"; then
      touch "$FAIL_PINGED"
    fi
  fi
fi

# mirror every class's blackboard content into its workdir. the files land
# outside the repo; the only repo output is .bb-mirror.json and any spec text it
# fills in, so it has to land before the commit below. it's 50-90 requests even
# when nothing changed, so on a poll run only do it when the scan moved a
# manifest or the last one is over 2h old
mirror=0
if [ "${CB_FORCE_MIRROR:-0}" = 1 ]; then
  mirror=1
elif [ -n "$(git status --porcelain -- 'classes/*/.bb-manifest.json')" ]; then
  echo "manifest changed, mirroring"
  mirror=1
elif [ ! -f "$MIRROR_STAMP" ] || [ -n "$(find "$MIRROR_STAMP" -mmin +120 2>/dev/null)" ]; then
  echo "last mirror over 2h ago, mirroring"
  mirror=1
fi
if [ "$mirror" = 1 ]; then
  if /usr/bin/python3 scripts/blackboard-mirror.py; then
    touch "$MIRROR_STAMP"
  else
    echo "blackboard mirror failed"
  fi
else
  echo "mirror skipped (nothing changed, last run under 2h ago)"
fi

# keep the workdir copies of the rulebook fresh. class-folder agent sessions
# import _course-brain-rules.md relatively (imports can't reach outside the
# project dir), so each workdir and the semester root carry a synced copy
grep -h '^workdir:' classes/*/class.md \
  | sed 's/^workdir: *//; s/[[:space:]]*#.*$//; s/^"//; s/"$//' \
  | while IFS= read -r wd; do
  # a class whose workdir isn't filled in yet leaves wd empty, and dirname ""
  # is "." - without this the rulebook lands in the repo root and gets committed
  [ -n "$wd" ] || continue
  [ -d "$wd" ] && cp CLAUDE.md "$wd/_course-brain-rules.md"
  sem=$(dirname "$wd")
  [ -d "$sem" ] && cp CLAUDE.md "$sem/_course-brain-rules.md"
done 2>/dev/null || echo "rulebook copy failed"

if [ "$DRY" = 1 ]; then
  echo "dry run: stopping before todoist, commit, push, schedule and pings"
  echo "would stage ($STAGE):"
  git status --short
  exit 0
fi

# after the scan so new assignment files get tasks in the same run
/usr/bin/python3 scripts/todoist-sync.py || echo "todoist sync failed"

if [ "$STAGE" = all ]; then
  git add -A
else
  # a failed claude run can leave half-written lecture files; stage only the
  # scan and todoist outputs, lectures stay uncommitted until the next good run
  # (per-spec, guarded: git add fatals on any pathspec matching nothing)
  for spec in 'classes/*/assignments/*' 'classes/*/.bb-manifest.json' \
              'classes/*/.bb-mirror.json' inbox; do
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
if git remote get-url origin >/dev/null 2>&1; then
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
# a full url) in ~/.course-brain/ntfy-topic. it goes last, and only after a
# successful push, so tapping it always lands on a repo that already has the
# flags. decision-only: it fires just for review-file entries that haven't been
# pinged before, so routine syncs stay silent. state file = flag headings
# already pinged; each flag pings exactly once — removals never ping, and a flag
# filed on a run whose push failed still pings on the next successful one
PINGED="$STATE/pinged-flags"
if [ "$pushed" = 1 ] && [ -f inbox/blackboard-review.md ]; then
  touch "$PINGED"
  new_flags=$(grep '^## ' inbox/blackboard-review.md | grep -Fxv -f "$PINGED" || true)
  if [ -n "$new_flags" ]; then
    count=$(printf '%s\n' "$new_flags" | wc -l | tr -d ' ')
    body=$(printf '%s\n' "$new_flags" | head -12 | sed 's/^## //')
    if [ "$count" -gt 12 ]; then
      body="$body
+$((count - 12)) more"
    fi
    body="$body
Decide via claude.ai/code — \"process the blackboard review file\""
    # a failed ping isn't recorded as pinged; it retries next run
    if ping_phone "course-brain: decision needed" "$body"; then
      printf '%s\n' "$new_flags" >> "$PINGED"
    fi
  else
    echo "no new review flags, no ping"
  fi
fi
