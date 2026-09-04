#!/usr/bin/env python3
# repo linter: class.md wiring, lecture files, assignment files, inbox hygiene.
# usage: python3 scripts/check.py [repo-root]
# exits 1 if anything is wrong, 0 otherwise. warnings don't fail the run.

import importlib.util
import re
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

# gen-schedule.py has a hyphen in the name, so load it by path instead of importing.
# sharing SEG + frontmatter keeps the two scripts from drifting apart.
_spec = importlib.util.spec_from_file_location("gen_schedule", HERE / "gen-schedule.py")
gen_schedule = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_schedule)
SEG = gen_schedule.SEG
frontmatter = gen_schedule.frontmatter

ID_FIELDS = ("granola_id", "source_id")
STATUSES = {"open", "submitted", "graded"}
ROLES = {"student", "ta"}
WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TRANSCRIPT = re.compile(r"^## Transcript\s*$", re.M)

problems = []
warnings = []


def bad(rel, msg):
    problems.append(f"{rel}: {msg}")


def warn(rel, msg):
    warnings.append(f"{rel}: warn: {msg}")


def iso_date(value):
    if not ISO_DATE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def iso_due(value):
    d = iso_date(value)
    if d:
        return d
    try:
        return datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None


def check_class(md, rel):
    fm = frontmatter(md)
    for field in ("code", "name", "schedule", "starts"):
        if not fm.get(field):
            bad(rel, f"missing frontmatter field '{field}'")
    code = fm.get("code", "")
    if code and md.parent.name != code.lower():
        bad(rel, f"directory is '{md.parent.name}' but code is '{code}' "
                 f"(expected classes/{code.lower()}/)")
    for seg in fm.get("schedule", "").split(","):
        seg = seg.strip()
        if not seg:
            continue
        if not SEG.match(seg):
            bad(rel, f"can't parse schedule segment '{seg}' "
                     "(want days MTWRF + 24h HH:MM-HH:MM)")
    starts = ends = None
    for field in ("starts", "ends"):
        raw = fm.get(field, "")
        if not raw:
            continue
        parsed = iso_date(raw)
        if not parsed:
            bad(rel, f"{field} '{raw}' is not a YYYY-MM-DD date")
        elif field == "starts":
            starts = parsed
        else:
            ends = parsed
    if starts and ends and starts >= ends:
        bad(rel, f"starts {starts} is not before ends {ends}")
    role = fm.get("role", "student")
    if role not in ROLES:
        bad(rel, f"role '{role}' is not one of {'/'.join(sorted(ROLES))}")
    if not fm.get("granola_folder_id"):
        warn(rel, "granola_folder_id is empty; lecture-sync will try to match by title")
    day = fm.get("discussion_initial_post", "")
    if day and day.lower() not in WEEKDAYS:
        bad(rel, f"discussion_initial_post '{day}' is not a weekday name")
    return code


def check_lecture(md, rel, code, seen_ids):
    fm = frontmatter(md)
    text = md.read_text()
    for field in ("class", "date"):
        if not fm.get(field):
            bad(rel, f"missing frontmatter field '{field}'")
    prefix = md.stem[:10]
    if fm.get("date") and fm["date"] != prefix:
        bad(rel, f"date '{fm['date']}' doesn't match filename prefix '{prefix}'")
    if not iso_date(prefix):
        bad(rel, "filename must start with a YYYY-MM-DD date")
    if fm.get("class") and code and fm["class"] != code:
        bad(rel, f"class '{fm['class']}' doesn't match class.md code '{code}'")
    if not TRANSCRIPT.search(text):
        bad(rel, "no '## Transcript' heading")
    # granola_id for granola meetings, source_id for anything imported by
    # lecture-import.py. exactly one, and no id used twice
    ids = [f for f in ID_FIELDS if fm.get(f)]
    if not ids:
        bad(rel, f"needs one of {' or '.join(ID_FIELDS)} in frontmatter")
    elif len(ids) > 1:
        bad(rel, f"has both {' and '.join(ids)}; keep exactly one")
    else:
        lid = fm[ids[0]]
        if lid in seen_ids:
            bad(rel, f"duplicate lecture id '{lid}' (also in {seen_ids[lid]})")
        else:
            seen_ids[lid] = rel


def check_assignment(md, rel):
    fm = frontmatter(md)
    if not fm.get("title"):
        bad(rel, "missing frontmatter field 'title'")
    due = fm.get("due", "")
    if not due:
        bad(rel, "missing frontmatter field 'due'")
    elif not iso_due(due):
        bad(rel, f"due '{due}' is not an ISO date or datetime")
    status = fm.get("status", "")
    if status not in STATUSES:
        bad(rel, f"status '{status}' is not one of {'/'.join(sorted(STATUSES))}")
    # todoist-sync matches the exact string "true"; True/yes would silently sync date-only
    if "calendar" in fm and fm["calendar"] not in ("true", "false"):
        bad(rel, f"calendar '{fm['calendar']}' must be exactly 'true' or 'false'")


def main():
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE.parent
    seen_ids = {}

    for class_dir in sorted(p for p in (repo / "classes").glob("*") if p.is_dir()):
        rel_dir = class_dir.relative_to(repo)
        md = class_dir / "class.md"
        code = ""
        if class_dir.name != "_template":
            if not md.exists():
                bad(rel_dir, "no class.md")
            else:
                code = check_class(md, md.relative_to(repo))
        elif md.exists():
            code = frontmatter(md).get("code", "")

        for lec in sorted(class_dir.glob("lectures/*.md")):
            check_lecture(lec, lec.relative_to(repo), code, seen_ids)
        for a in sorted(class_dir.glob("assignments/*.md")):
            if a.name == "_template.md":
                continue
            check_assignment(a, a.relative_to(repo))

    # a conflicted file would otherwise lint clean and get auto-committed by the
    # scheduled job
    for md_file in sorted(list((repo / "classes").rglob("*.md")) + list((repo / "inbox").glob("*.md"))):
        for n, line in enumerate(md_file.read_text().splitlines(), 1):
            if line.startswith(("<<<<<<< ", ">>>>>>> ")):
                bad(md_file.relative_to(repo), f"line {n}: merge conflict marker")
                break

    inbox = repo / "inbox"
    if inbox.is_dir():
        for p in sorted(inbox.iterdir()):
            if p.is_dir():
                bad(p.relative_to(repo), "inbox is flat; file this under a class instead")

    for line in warnings:
        print(line)
    for line in problems:
        print(line)
    if problems:
        print(f"{len(problems)} problem(s)")
        return 1
    print("clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
