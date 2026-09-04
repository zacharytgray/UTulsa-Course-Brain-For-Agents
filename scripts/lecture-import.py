#!/usr/bin/env python3
# file a lecture transcript from any source (whisper output, another notetaker's
# export, a pasted file) into classes/<class>/lectures/. the granola skill has
# its own path; this is the one for everything else.
# usage:
#   python3 scripts/lecture-import.py <class-code> <transcript-file> \
#       --date YYYY-MM-DD [--title "..."] [--summary <file>] [--id <stable-id>]
# CB_REPO_ROOT overrides which tree it writes into (tests use it).

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

REPO = Path(os.environ.get("CB_REPO_ROOT") or Path(__file__).resolve().parent.parent)
ID_FIELDS = ("granola_id", "source_id")
NO_SUMMARY = "Summary not written yet. Write one from the transcript below."


def frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([\w-]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    return fm


def already_filed(lectures, source_id):
    # an id already in the tree means this transcript is filed, whichever
    # field it landed under
    for md in sorted(lectures.glob("*.md")):
        fm = frontmatter(md.read_text())
        if any(fm.get(f) == source_id for f in ID_FIELDS):
            return md
    return None


def free_path(lectures, date):
    # same date, different lecture: -2, -3, like the granola skill does
    path = lectures / f"{date}.md"
    n = 2
    while path.exists():
        path = lectures / f"{date}-{n}.md"
        n += 1
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("transcript")
    ap.add_argument("--date", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--id", default="")
    args = ap.parse_args()

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        sys.exit(f"--date '{args.date}' is not a YYYY-MM-DD date")

    class_dir = REPO / "classes" / args.code.lower()
    class_md = class_dir / "class.md"
    if not class_md.exists():
        sys.exit(f"no class.md for '{args.code}' (looked in {class_dir})")
    code = frontmatter(class_md.read_text()).get("code") or args.code

    transcript = Path(args.transcript).read_text().strip()
    summary = Path(args.summary).read_text().strip() if args.summary else NO_SUMMARY
    source_id = args.id or hashlib.sha256(transcript.encode()).hexdigest()[:12]

    lectures = class_dir / "lectures"
    lectures.mkdir(exist_ok=True)
    filed = already_filed(lectures, source_id)
    if filed:
        print(f"already filed as {filed.relative_to(REPO)} (id {source_id})")
        return 0

    title = args.title or f"{code} lecture {args.date}"
    title = title.replace("\\", "\\\\").replace('"', '\\"')  # keep the yaml quoting valid
    path = free_path(lectures, args.date)
    path.write_text(
        "---\n"
        f"source_id: {source_id}\n"
        f"class: {code}\n"
        f"date: {args.date}\n"
        f'title: "{title}"\n'
        "topics: []\n"
        "---\n\n"
        f"# {code} — {args.date}\n\n"
        f"{summary}\n\n"
        "## Transcript\n\n"
        f"{transcript}\n")
    print(f"wrote {path.relative_to(REPO)} (id {source_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
