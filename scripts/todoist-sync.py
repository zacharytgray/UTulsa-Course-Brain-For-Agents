#!/usr/bin/env python3
# sync assignment files to todoist: create tasks for new ones, refresh
# descriptions and due dates on the rest, and pull task comments back into the
# file under "## Notes". descriptions and dates are machine-owned (the file is
# the source of truth, so a due moved in todoist by hand snaps back next run);
# comments are the user's notes zone - read and mirrored, never written or deleted.
# checking a task off in todoist is the one thing that flows the other way: it
# flips the file to submitted.
import glob
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

API = "https://api.todoist.com/api/v1"


def token():
    if os.environ.get("TODOIST_API_TOKEN"):
        return os.environ["TODOIST_API_TOKEN"]
    p = os.path.expanduser("~/.config/todoist/token")
    if os.path.exists(p):
        return open(p).read().strip()
    sys.exit("no todoist token (TODOIST_API_TOKEN env or ~/.config/todoist/token)")


TOKEN = token()


def req(path, data=None):
    # `data is not None`, not `data`: close takes an empty POST body, and a falsy {}
    # would turn it into a GET (405 on /close)
    r = urllib.request.Request(API + path,
                               headers={"Authorization": f"Bearer {TOKEN}",
                                        "Content-Type": "application/json"},
                               data=json.dumps(data).encode() if data is not None else None)
    body = urllib.request.urlopen(r).read()
    return json.loads(body) if body else None


def frontmatter(text):
    parts = text.split("---")
    # [ \t] not \s: \s spans newlines, so an empty key (posted:) would swallow the next line
    fm = dict(re.findall(r"(?m)^(\w+):[ \t]*(.*)$", parts[1]))
    return {k: v.strip().strip('"') for k, v in fm.items()}, "---".join(parts[2:]).strip()


def strip_notes(body):
    return body.split("\n## Notes")[0].rstrip()


def pretty_due(due):
    # "2026-10-14T23:59" -> "2026-10-14 11:59 PM"; date-only passes through
    if "T" not in due:
        return due
    try:
        return datetime.fromisoformat(due).strftime("%Y-%m-%d %-I:%M %p")
    except ValueError:
        return due.replace("T", " ")


def local_ts(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def pull_comments(path, text, tid):
    try:
        res = req(f"/comments?task_id={tid}")
        comments = res.get("results", res) if isinstance(res, dict) else res
    except Exception as e:
        print(f"comments fetch failed {path}: {e}", file=sys.stderr)
        return text, 0
    seen = set(re.findall(r"<!-- tid:(\S+) -->", text))
    new = [c for c in comments if str(c["id"]) not in seen and c.get("content", "").strip()]
    if not new:
        return text, 0
    if "## Notes" not in text:
        text = text.rstrip() + "\n\n## Notes\n"
    for c in sorted(new, key=lambda c: c.get("posted_at", "")):
        content = c["content"].strip().replace("\n", "\n  ")
        text = text.rstrip() + f"\n- {local_ts(c.get('posted_at', ''))} — {content} <!-- tid:{c['id']} -->\n"
    open(path, "w").write(text)
    return text, len(new)


def completed(tid):
    # completed tasks drop out of the active list, so ask for the task itself.
    # a 404 means deleted, not done - leave the file alone
    try:
        return bool(req(f"/tasks/{tid}").get("checked"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def mark_submitted(path, text):
    text = re.sub(r"(?m)^status:[ \t]*open[ \t]*$", "status: submitted", text, count=1)
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    if not re.search(r"(?m)^## Submitted\s*$", text):
        text = text.rstrip() + f"\n\n## Submitted\n\nMarked complete in Todoist on {today}.\n"
    open(path, "w").write(text)
    return text


def project_id(name):
    for p in req("/projects")["results"]:
        if p["name"] == name:
            return p["id"]
    return req("/projects", {"name": name})["id"]


def main():
    only = sys.argv[1].lower() if len(sys.argv) > 1 else None
    projects = {}
    created = refreshed = closed = notes = submitted = 0
    for cls_md in sorted(glob.glob("classes/*/class.md")):
        cdir = os.path.dirname(cls_md)
        if cdir.endswith("_template"):
            continue
        cfm, _ = frontmatter(open(cls_md).read())
        code = cfm.get("code", "")
        if only and code.lower() != only:
            continue
        if cfm.get("role") == "ta":
            continue  # ta class files are things to grade, not do
        proj = cfm.get("todoist_project") or "School"
        for f in sorted(glob.glob(f"{cdir}/assignments/*.md")):
            if f.endswith("_template.md"):
                continue
            text = open(f).read()
            fm, body = frontmatter(text)
            tid = fm.get("todoist_task_id", "")
            if tid and fm.get("status") == "open":
                if completed(tid):
                    mark_submitted(f, text)
                    submitted += 1
                    print(f"submitted (checked off in todoist): {f}")
                    continue
                text, n = pull_comments(f, text, tid)
                if n:
                    notes += n
                    print(f"notes +{n}: {f}")
                    fm, body = frontmatter(text)
            due_line = f"\nDue: {pretty_due(fm['due'])}" if fm.get("due") else ""
            desc = f"{f}{due_line}\n\n{strip_notes(body)}"[:16000]
            # date-only unless calendar: true — timed tasks sync to the calendar
            # todoist is connected to, and only exams/presentations belong there.
            # the time still shows in the Due: line of the description.
            due = None
            if fm.get("due"):
                due = fm["due"].replace("T", " ") if fm.get("calendar") == "true" else fm["due"][:10]
            if fm.get("status") in ("submitted", "graded"):
                if tid:
                    try:
                        req(f"/tasks/{tid}/close", {})
                        closed += 1
                    except Exception as e:
                        print(f"close failed {f}: {e}", file=sys.stderr)
                continue
            if tid:
                # due and title ride along on the refresh so a moved deadline (or
                # a calendar: true added later, or a retitled file) reaches the task
                upd = {"description": desc, "content": f"[{code}] {fm['title']}"}
                if due:
                    upd["due_string"] = due
                req(f"/tasks/{tid}", upd)
                refreshed += 1
                continue
            if not due:
                print(f"skip (no due): {f}")
                continue
            if proj not in projects:
                projects[proj] = project_id(proj)
            t = req("/tasks", {"content": f"[{code}] {fm['title']}",
                               "project_id": projects[proj],
                               "due_string": due,
                               "description": desc})
            # empty field can be `todoist_task_id: ""` or a bare `todoist_task_id:`;
            # a missed replace here silently drops the id and the next run duplicates the task
            new = re.sub(r'(?m)^todoist_task_id:\s*(?:""|\'\')?\s*$',
                         f'todoist_task_id: "{t["id"]}"', text, count=1)
            if new == text:
                print(f"WARNING: could not write id {t['id']} into {f}")
            open(f, "w").write(new)
            created += 1
            print(f"created {t['id']}  [{code}] {fm['title']}")
    print(f"{created} created, {refreshed} refreshed (desc+due), {closed} closed, "
          f"{submitted} marked submitted, {notes} notes pulled")


if __name__ == "__main__":
    main()
