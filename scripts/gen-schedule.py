#!/usr/bin/env python3
# regenerate the launchd schedule from class.md schedules.
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
LABEL = "com.course-brain.lecture-sync"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
JOB = REPO / "scripts" / "lecture-sync-job.sh"
LOG_DIR = Path.home() / "Library/Logs/course-brain"

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


def main():
    dry = "--dry-run" in sys.argv
    cal = [{"Weekday": w, "Hour": h, "Minute": m} for w, h, m in entries()]
    if dry:
        for e in cal:
            print(f"weekday {e['Weekday']} at {e['Hour']:02d}:{e['Minute']:02d}")
        print(f"{len(cal)} run times (dry run, nothing installed)")
        return
    plist = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/zsh", str(JOB)],
        "StartCalendarInterval": cal,
        "RunAtLoad": False,
        "StandardOutPath": str(LOG_DIR / "launchd.log"),
        "StandardErrorPath": str(LOG_DIR / "launchd.log"),
    }
    data = plistlib.dumps(plist)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if PLIST.exists() and PLIST.read_bytes() == data:
        print(f"schedule unchanged ({len(cal)} run times)")
        return
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(data)
    uid = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
    reload_cmd = (f"launchctl bootout gui/{uid}/{LABEL} 2>/dev/null; "
                  f"launchctl bootstrap gui/{uid} '{PLIST}' || launchctl load '{PLIST}'")
    if os.environ.get("COURSE_BRAIN_FROM_JOB"):
        # we're running inside the service we'd be booting out — bootout would
        # kill us mid-flight. hand the reload to a detached process instead.
        subprocess.Popen(["/bin/zsh", "-c", f"sleep 5; {reload_cmd}"],
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"{len(cal)} run times -> {PLIST}; reload handed to detached process")
    else:
        subprocess.run(["/bin/zsh", "-c", reload_cmd], check=True)
        print(f"installed {len(cal)} run times -> {PLIST}")


if __name__ == "__main__":
    main()
