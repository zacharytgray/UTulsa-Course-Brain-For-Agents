#!/usr/bin/env python3
# diff blackboard's gradebook + content tree against the repo. files new graded
# assignments, fixes due dates that moved, and flags anything ambiguous to
# inbox/blackboard-review.md. never logs in itself - scripts/bb handles the
# session (and relogins once on its own). state lives in each class's
# .bb-manifest.json so a second run with no upstream changes touches nothing.
import glob
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = ZoneInfo("America/Chicago")
SUMMARY = "/tmp/course-brain-scan-summary"
REVIEW = "inbox/blackboard-review.md"
SKIP = ("attendance", "overall grade")

REVIEW_HEADER = """# Blackboard review

Flagged Blackboard changes that need a human decision. To process from anywhere: open
claude.ai/code on this repo (works from a phone) and say "process the blackboard
review file". Apply or reject each entry, delete handled entries, commit and push —
Todoist reconciles on the next scheduled sync run.
"""


def frontmatter(text):
    parts = text.split("---")
    fm = dict(re.findall(r"(?m)^(\w+):\s*(.*)$", parts[1]))
    return {k: v.strip().strip('"') for k, v in fm.items()}, "---".join(parts[2:]).strip()


def bb_get(path):
    r = subprocess.run([f"{REPO}/scripts/bb", "get", path, "--raw"],
                       capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "bb get failed")
    return json.loads(r.stdout)


def fetch_all(path):
    out = []
    while path:
        data = bb_get(path)
        out += data.get("results", [])
        path = (data.get("paging") or {}).get("nextPage")
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def col_name(c):
    # "name" is null on harvey; the displayed name is effectiveColumnName
    return c.get("effectiveColumnName") or c.get("name") or ""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def local_due(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(LOCAL).strftime("%Y-%m-%dT%H:%M")


def due_matches(existing, incoming):
    if not existing:
        return False
    if len(existing) == 10:
        return existing == incoming[:10]
    return existing.replace(" ", "T")[:16] == incoming[:16]


def keep(cols, starts, ends):
    # stale duplicates hang around with old dates; prefer one due inside the semester
    def rank(c):
        d = c.get("dueDate")
        local = local_due(d)[:10] if d else ""
        return (bool(local and starts <= local <= ends), local)
    return max(cols, key=rank)


def match_files(cdir, name):
    n = norm(name)
    if not n:
        # an all-punctuation name would substring-match every file
        return []
    titles = {}
    for f in sorted(glob.glob(f"{cdir}/assignments/*.md")):
        if f.endswith("_template.md"):
            continue
        fm, _ = frontmatter(open(f).read())
        t = norm(fm.get("title", ""))
        if t:
            titles[f] = t
    hits = [f for f, t in titles.items() if t == n]
    if hits:
        return hits
    return [f for f, t in titles.items() if t in n or n in t]


def context_line(items, content_id):
    item = items.get(content_id)
    if not item:
        return ""
    chain, node, seen = [], item, set()
    while node and node.get("id") not in seen:
        seen.add(node.get("id"))
        chain.append(node)
        node = items.get(node.get("parentId"))
    ancestors = chain[1:]
    if not ancestors:
        return ""
    top = ancestors[-1].get("title", "")
    parent = ancestors[0].get("title", "")
    return f"{top}, under {parent}." if len(ancestors) > 1 else f"{top}."


def write_file(path, name, due, posted, source, context):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    name = name.replace('"', "'")  # a double quote would break the frontmatter
    fm = ["---", f'title: "{name}"', f"due: {due}", f"posted: {posted}".rstrip(),
          f'source: "{source}"', "status: open", 'todoist_task_id: ""', "---", ""]
    body = ([context] if context else []) + ["Full spec on Harvey (not yet mirrored)."]
    open(path, "w").write("\n".join(fm + body) + "\n")


def set_due(path, due):
    text = open(path).read()
    open(path, "w").write(re.sub(r"(?m)^due:.*$", f"due: {due}", text, count=1))


def add_review(code, short, name, due, points, paths, lead):
    if not os.path.exists(REVIEW):
        os.makedirs("inbox", exist_ok=True)
        open(REVIEW, "w").write(REVIEW_HEADER)
    lines = [f"\n## {date.today().isoformat()} — {code}: {short}", "",
             f'Blackboard shows a graded column "{name}", due {due or "no due date"}, '
             f'{points if points is not None else "unknown"} points.',
             "", lead]
    lines += [f"- `{p}`" for p in paths]
    lines += ["", "Options: match it to one of the files above and update that file's "
              f"`due:` to `{due}`, or create a new assignment file for it."]
    with open(REVIEW, "a") as f:
        f.write("\n".join(lines) + "\n")


def write_manifest(cdir, columns, contents):
    manifest = {
        "columns": {c["id"]: {"name": col_name(c), "dueDate": c.get("dueDate"),
                              "possible": c.get("possible"), "contentId": c.get("contentId")}
                    for c in columns},
        "contents": {i["id"]: {"title": i.get("title"), "parentId": i.get("parentId"),
                               "contentHandler": i.get("contentHandler")}
                     for i in contents},
    }
    path = f"{cdir}/.bb-manifest.json"
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if os.path.exists(path) and open(path).read() == text:
        return
    open(path, "w").write(text)


def scan(code, cdir, cfm, columns, contents):
    prev = None
    mpath = f"{cdir}/.bb-manifest.json"
    if os.path.exists(mpath):
        prev = json.load(open(mpath))
    known = set((prev or {}).get("columns", {}))
    items = {i["id"]: i for i in contents}

    wanted = [c for c in columns
              if col_name(c) and not any(s in col_name(c).lower() for s in SKIP)
              # zero-point knowledge checks aren't tracked; the few with extra credit are
              and not ("knowledge check" in col_name(c).lower() and not c.get("possible"))]
    by_name = {}
    for c in wanted:
        by_name.setdefault(norm(col_name(c)), []).append(c)
    # class.md keeps inline comments on these lines; drop them
    starts = cfm.get("starts", "").split("#")[0].strip()
    ends = cfm.get("ends", "").split("#")[0].strip()

    res = {"new": 0, "updated": 0, "flagged": 0, "notes": [], "content": [],
           "baseline": prev is None}
    for cols in by_name.values():
        col = cols[0] if len(cols) == 1 else keep(cols, starts, ends)
        name = col_name(col)
        due = local_due(col["dueDate"]) if col.get("dueDate") else ""
        hits = match_files(cdir, name)

        if len(hits) == 1:
            fm, _ = frontmatter(open(hits[0]).read())
            if due and not due_matches(fm.get("due", ""), due):
                set_due(hits[0], due)
                res["updated"] += 1
                res["notes"].append(f"due {due} → {os.path.basename(hits[0])}")
            continue

        if col["id"] in known:
            continue

        if len(hits) > 1:
            add_review(code, f'"{name}" matches more than one file', name, due,
                       col.get("possible"), hits,
                       "It matches more than one assignment file already in the repo:")
            res["flagged"] += 1
            continue

        if not due:
            res["notes"].append(f'new graded column with no due date: "{name}"')
            continue

        path = f"{cdir}/assignments/{slug(name)}.md"
        if os.path.exists(path):
            add_review(code, f'"{name}" collides with an existing file', name, due,
                       col.get("possible"), [path],
                       "Its slug is already taken, but the titles don't match:")
            res["flagged"] += 1
            continue

        item = items.get(col.get("contentId")) or {}
        posted = (item.get("created") or item.get("createdDate") or "")[:10]
        write_file(path, name, due, posted, cfm.get("blackboard_url", ""),
                   context_line(items, col.get("contentId")))
        res["new"] += 1
        res["notes"].append(f"new {os.path.basename(path)} (due {due})")

    if prev is not None:
        known_items = set(prev.get("contents", {}))
        res["content"] = [i.get("title") or i["id"] for i in contents if i["id"] not in known_items]
    return res


def main():
    os.chdir(REPO)
    argv = sys.argv[1:]
    skip_todoist = "--skip-todoist" in argv
    only = next((a.lower() for a in argv if not a.startswith("--")), None)

    new = updated = flagged = 0
    lines, failures = [], []
    for cls_md in sorted(glob.glob("classes/*/class.md")):
        cdir = os.path.dirname(cls_md)
        if cdir.endswith("_template"):
            continue
        cfm, _ = frontmatter(open(cls_md).read())
        code = cfm.get("code", "")
        url = cfm.get("blackboard_url", "")
        if not url or (only and code.lower() != only):
            continue
        m = re.search(r"_\d+_1", url)
        if not m:
            continue
        try:
            columns = fetch_all(f"/learn/api/v1/courses/{m.group(0)}/gradebook/columns?limit=200")
            contents = fetch_all(f"/learn/api/v1/courses/{m.group(0)}/contents"
                                 "?recursive=true&limit=300")
        except Exception as e:
            print(f"{code}: fetch failed: {e}", file=sys.stderr)
            failures.append(f"{code}: fetch failed, skipped")
            continue

        res = scan(code, cdir, cfm, columns, contents)
        write_manifest(cdir, columns, contents)
        new += res["new"]
        updated += res["updated"]
        flagged += res["flagged"]

        notes = list(res["notes"])
        if res["baseline"]:
            notes.append("baseline created")
        elif res["content"]:
            titles = res["content"][:5]
            more = f" +{len(res['content']) - 5} more" if len(res["content"]) > 5 else ""
            notes.append("new content: " + ", ".join(titles) + more)
        if notes:
            lines.append(f"{code}: " + "; ".join(notes))

    head = "Blackboard scan: no changes" if not (new or updated or flagged) else (
        f"Blackboard scan: {new} new, {updated} due updates, {flagged} flagged")
    out = [head] + lines + failures
    if flagged:
        out.append(f"Review flags await a decision — see {REVIEW}")
    text = "\n".join(out) + "\n"
    open(SUMMARY, "w").write(text)
    print(text, end="")

    if (new or updated) and not skip_todoist:
        subprocess.run([sys.executable, "scripts/todoist-sync.py"])
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
