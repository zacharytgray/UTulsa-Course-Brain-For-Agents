#!/usr/bin/env python3
# regenerate the launchd jobs: the class-driven lecture sync, and the fixed
# 30-min blackboard poll (--no-poll skips and removes that one).
# each class meeting adds a sync run 30 min after the class ends, plus a
# weekday 07:05 refresh run so schedule changes propagate on their own.
# the job script re-runs this after every sync, so editing a class.md
# is enough to keep the schedule current.

import os
import plistlib
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS = Path.home() / "Library/LaunchAgents"
LOG_DIR = Path.home() / "Library/Logs/course-brain"

LABEL = "com.course-brain.lecture-sync"
PLIST = AGENTS / f"{LABEL}.plist"
JOB = REPO / "scripts" / "lecture-sync-job.sh"

POLL_LABEL = "com.course-brain.blackboard-poll"
POLL_PLIST = AGENTS / f"{POLL_LABEL}.plist"
POLL_JOB = REPO / "scripts" / "blackboard-poll-job.sh"
POLL_INTERVAL = 1800

# launchd weekday: 1=Mon .. 5=Fri. R is thursday.
DAY = {"M": 1, "T": 2, "W": 3, "R": 4, "F": 5}
SEG = re.compile(r"^([MTWRF]+)\s+(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})$")


def frontmatter(path):
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([\w-]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = _value(m.group(2))
    return fm


def _value(raw):
    # quoted values are taken whole; otherwise a comment starts at " #",
    # same as yaml, so "HW #1" and url#fragment survive
    raw = raw.strip()
    q = re.match(r'^"([^"]*)"|^\'([^\']*)\'', raw)
    if q:
        return q.group(1) if q.group(1) is not None else q.group(2)
    if raw.startswith("#"):
        return ""
    return raw.split(" #")[0].strip()


def ended(fm, md):
    # no ends date means the class never expires
    raw = fm.get("ends", "")
    if not raw:
        return False
    try:
        return date.fromisoformat(raw) < date.today()
    except ValueError:
        print(f"warn: can't parse ends '{raw}' in {md}", file=sys.stderr)
        return False


def entries():
    out = set()
    for wd in DAY.values():  # weekday refresh runs
        out.add((wd, 7, 5))
    for md in sorted(REPO.glob("classes/*/class.md")):
        if md.parent.name == "_template":
            continue
        fm = frontmatter(md)
        sched = fm.get("schedule", "")
        if not sched:
            continue
        if ended(fm, md):
            print(f"note: {md.parent.name} ended {fm['ends']}, skipping its runs",
                  file=sys.stderr)
            continue
        # format: "MWF 10:00-10:50" or "MW 10:00-11:15, F 9:00-9:50"
        for seg in sched.split(","):
            m = SEG.match(seg.strip())
            if not m:
                print(f"warn: can't parse '{seg.strip()}' in {md}", file=sys.stderr)
                continue
            days, _, _, eh, em = m.groups()
            if int(eh) < 7:
                print(f"warn: '{seg.strip()}' in {md} ends before 07:00 — "
                      "times must be 24-hour", file=sys.stderr)
            minute = int(em) + 30
            hour = int(eh) + minute // 60
            minute %= 60
            if hour > 23:
                print(f"warn: '{seg.strip()}' in {md} rolls past midnight, "
                      "clamping to 23:59", file=sys.stderr)
                hour, minute = 23, 59
            for d in days:
                out.add((DAY[d], hour, minute))
    return sorted(out)


def job_plist(label, job, extra):
    p = {
        "Label": label,
        "ProgramArguments": ["/bin/zsh", str(job)],
        "RunAtLoad": False,
        # launchd agents default to OFF, and a cloud-synced workdir whose files
        # aren't downloaded yet then returns EDEADLK
        "MaterializeDatalessFiles": True,
        "StandardOutPath": str(LOG_DIR / "launchd.log"),
        "StandardErrorPath": str(LOG_DIR / "launchd.log"),
    }
    p.update(extra)
    return p


def uid():
    return subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()


def install(label, path, plist, what):
    data = plistlib.dumps(plist)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        print(f"{label} unchanged ({what})")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    reload_cmd = (f"launchctl bootout gui/{uid()}/{label} 2>/dev/null; "
                  f"launchctl bootstrap gui/{uid()} '{path}' || launchctl load '{path}'")
    if os.environ.get("COURSE_BRAIN_FROM_JOB"):
        # we're running inside the service we'd be booting out — bootout would
        # kill us mid-flight. hand the reload to a detached process instead.
        subprocess.Popen(["/bin/zsh", "-c", f"sleep 5; {reload_cmd}"],
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"{what} -> {path}; reload handed to detached process")
    else:
        subprocess.run(["/bin/zsh", "-c", reload_cmd], check=True)
        print(f"installed {what} -> {path}")


def uninstall(label, path):
    if not path.exists():
        return
    subprocess.run(["/bin/zsh", "-c", f"launchctl bootout gui/{uid()}/{label} 2>/dev/null; true"])
    path.unlink()
    print(f"removed {label}")


def main():
    dry = "--dry-run" in sys.argv
    poll = "--no-poll" not in sys.argv
    cal = [{"Weekday": w, "Hour": h, "Minute": m} for w, h, m in entries()]
    lecture = job_plist(LABEL, JOB, {"StartCalendarInterval": cal})
    # fixed interval, no calendar: the poll gates its own hours in the script
    poll_plist_data = job_plist(POLL_LABEL, POLL_JOB, {"StartInterval": POLL_INTERVAL})
    if dry:
        for e in cal:
            print(f"weekday {e['Weekday']} at {e['Hour']:02d}:{e['Minute']:02d}")
        print(f"{len(cal)} {LABEL} run times" + (
            f", plus {POLL_LABEL} every {POLL_INTERVAL // 60} min" if poll else
            ", no blackboard poll") + " (dry run, nothing installed)")
        print(f"  {LABEL}: /bin/zsh {JOB}")
        if poll:
            print(f"  {POLL_LABEL}: /bin/zsh {POLL_JOB}")
        return
    install(LABEL, PLIST, lecture, f"{len(cal)} run times")
    if poll:
        install(POLL_LABEL, POLL_PLIST, poll_plist_data, f"every {POLL_INTERVAL // 60} min")
    else:
        uninstall(POLL_LABEL, POLL_PLIST)


if __name__ == "__main__":
    main()
