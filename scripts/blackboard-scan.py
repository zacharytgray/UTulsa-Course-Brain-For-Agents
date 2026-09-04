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
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = ZoneInfo("America/Chicago")
SUMMARY = "/tmp/course-brain-scan-summary"
REVIEW = "inbox/blackboard-review.md"
SKIP = ("attendance", "overall grade")
FORUM = "resource/x-bb-forumlink"
COURSELINK = "resource/x-bb-courselink"
# strips the prefix off a blackboard title so pair titles never double it
DISC_PREFIX = re.compile(r"(?i)^\s*discussion(?:\s+reply)?\s*:\s*")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

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


def link_info(cid, content_id, items, cache):
    # (contentHandler, courselink target). forum items live outside the ultra
    # tree and gradebook columns point straight at them, so anything missing
    # gets fetched by id - cached in the manifest, one request per id ever
    if not content_id:
        return "", ""
    item = items.get(content_id)
    if item is None:
        if content_id not in cache:
            try:
                item = bb_get(f"/learn/api/v1/courses/{cid}/contents/{content_id}")
            except Exception:
                item = {}
            detail = (item.get("contentDetail") or {}).get(COURSELINK) or {}
            cache[content_id] = [item.get("contentHandler") or "",
                                 detail.get("linkSourceId") or ""]
        return tuple(cache[content_id])
    detail = (item.get("contentDetail") or {}).get(COURSELINK) or {}
    return item.get("contentHandler") or "", detail.get("linkSourceId") or ""


def is_discussion(cid, content_id, items, cache):
    # by type, never by title - plenty of discussions carry no "Discussion:" prefix
    handler, target = link_info(cid, content_id, items, cache)
    if handler == COURSELINK and target:
        handler, _ = link_info(cid, target, items, cache)
    return handler == FORUM


def topic(name):
    return DISC_PREFIX.sub("", name).strip()


def weekday_before(due, day):
    # the initial post is due on the named weekday ahead of the reply deadline
    d = date.fromisoformat(due[:10])
    return (d - timedelta(days=((d.weekday() - WEEKDAYS.index(day)) % 7) or 7)).isoformat()


def initial_post_day(cfm):
    # opt-in per class: "discussion_initial_post: friday" in class.md frontmatter
    day = cfm.get("discussion_initial_post", "").split("#")[0].strip().lower()
    return day if day in WEEKDAYS else ""


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
        # the initial-post half of a discussion pair has no gradebook column of
        # its own; letting it match would push the reply due date onto it
        if f.endswith("_template.md") or f.endswith("-initial-post.md"):
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


def write_file(path, name, due, posted, source, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    name = name.replace('"', "'")  # a double quote would break the frontmatter
    fm = ["---", f'title: "{name}"', f"due: {due}", f"posted: {posted}".rstrip(),
          f'source: "{source}"', "status: open", 'todoist_task_id: ""', "---", ""]
    open(path, "w").write("\n".join(fm + body) + "\n")


def write_pair(cdir, name, due, posted, source, context, day, dry):
    # classes that want an initial post ahead of the reply deadline get two
    # files; set discussion_initial_post in class.md to turn this on
    base = slug(name)
    reply = f"{cdir}/assignments/{base}.md"
    initial = f"{cdir}/assignments/{base}-initial-post.md"
    t = topic(name)
    first = weekday_before(due, day)
    rule = (f"discussions need an initial post by the {day.capitalize()} before the "
            "reply deadline")
    made = []
    if not os.path.exists(reply):
        body = ([context] if context else []) + [
            "Full spec on Harvey (not yet mirrored).",
            "",
            f"Initial post due {day.capitalize()} {first} ({rule}).",
            "",
            f"Initial post tracked separately in `{os.path.basename(initial)}`.",
        ]
        if not dry:
            write_file(reply, f"Discussion Reply: {t}", due, posted, source, body)
        made.append(reply)
    if not os.path.exists(initial):
        body = [f"Initial post for the discussion tracked in `{os.path.basename(reply)}` "
                "(full deadline later).",
                f"Per the class's deadline rules: {rule}."]
        if not dry:
            write_file(initial, f"Discussion: {t}", f"{first}T23:59", posted, source, body)
        made.append(initial)
    return made


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
    if due:
        lines += ["", "Options: match it to one of the files above and update that file's "
                  f"`due:` to `{due}`, or create a new assignment file for it."]
    else:
        lines += ["", "Options: create an assignment file for it with a due date of your "
                  "choosing, or ignore the column."]
    with open(REVIEW, "a") as f:
        f.write("\n".join(lines) + "\n")


def write_manifest(cdir, columns, contents, links):
    manifest = {
        "columns": {c["id"]: {"name": col_name(c), "dueDate": c.get("dueDate"),
                              "possible": c.get("possible"), "contentId": c.get("contentId")}
                    for c in columns},
        "contents": {i["id"]: {"title": i.get("title"), "parentId": i.get("parentId"),
                               "contentHandler": i.get("contentHandler")}
                     for i in contents},
        "links": links,
    }
    path = f"{cdir}/.bb-manifest.json"
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if os.path.exists(path) and open(path).read() == text:
        return
    open(path, "w").write(text)


def scan(code, cdir, cfm, cid, columns, contents, dry=False):
    prev = None
    mpath = f"{cdir}/.bb-manifest.json"
    if os.path.exists(mpath):
        prev = json.load(open(mpath))
    known = set((prev or {}).get("columns", {}))
    links = dict((prev or {}).get("links", {}))
    items = {i["id"]: i for i in contents}
    day = initial_post_day(cfm)

    # whole-name match only - a column like "Session 5 - Attendance" is a real
    # assignment, and a zero-point knowledge check is still worth tracking
    skip = {norm(s) for s in SKIP}
    wanted = [c for c in columns if col_name(c) and norm(col_name(c)) not in skip]
    by_name = {}
    for c in wanted:
        by_name.setdefault(norm(col_name(c)), []).append(c)
    # class.md keeps inline comments on these lines; drop them
    starts = cfm.get("starts", "").split("#")[0].strip()
    ends = cfm.get("ends", "").split("#")[0].strip()

    res = {"new": 0, "updated": 0, "flagged": 0, "notes": [], "content": [],
           "baseline": prev is None, "discussions": [], "links": links}
    for cols in by_name.values():
        col = cols[0] if len(cols) == 1 else keep(cols, starts, ends)
        name = col_name(col)
        due = local_due(col["dueDate"]) if col.get("dueDate") else ""
        item = items.get(col.get("contentId")) or {}
        disc = bool(due) and is_discussion(cid, col.get("contentId"), items, links)
        if disc:
            # a forum item's gradebook time is a creation stamp, not the deadline
            due = f"{due[:10]}T23:59"
            base = f"{cdir}/assignments/{slug(name)}"
            d = {"name": name, "due": due, "pair": bool(day),
                 "file": f"{base}.md"}
            if day:
                d.update({"initial": weekday_before(due, day),
                          "initial_title": f"Discussion: {topic(name)}",
                          "reply_title": f"Discussion Reply: {topic(name)}",
                          "initial_file": f"{base}-initial-post.md"})
            res["discussions"].append(d)
        hits = match_files(cdir, name)

        if len(hits) == 1:
            fm, _ = frontmatter(open(hits[0]).read())
            # discussions own their own time, so the gradebook never moves them
            if due and not disc and not due_matches(fm.get("due", ""), due):
                if not dry:
                    set_due(hits[0], due)
                res["updated"] += 1
                res["notes"].append(f"due {due} → {os.path.basename(hits[0])}")
            continue

        if col["id"] in known:
            continue

        if len(hits) > 1:
            if not dry:
                add_review(code, f'"{name}" matches more than one file', name, due,
                           col.get("possible"), hits,
                           "It matches more than one assignment file already in the repo:")
            res["flagged"] += 1
            continue

        if not due:
            # participation columns get made mid-session with no date; flag once
            # so it reaches a decision instead of dropping into the summary
            if not dry:
                add_review(code, f'"{name}" has no due date', name, due,
                           col.get("possible"), [],
                           "It's graded but has no due date on Blackboard, so the scan "
                           "can't file it on its own.")
            res["flagged"] += 1
            continue

        path = f"{cdir}/assignments/{slug(name)}.md"
        posted = (item.get("created") or item.get("createdDate") or "")[:10]
        context = context_line(items, col.get("contentId"))
        source = cfm.get("blackboard_url", "")

        if disc and day:
            for made in write_pair(cdir, name, due, posted, source, context, day, dry):
                res["new"] += 1
                res["notes"].append(f"new {os.path.basename(made)}")
            continue

        if os.path.exists(path):
            if not dry:
                add_review(code, f'"{name}" collides with an existing file', name, due,
                           col.get("possible"), [path],
                           "Its slug is already taken, but the titles don't match:")
            res["flagged"] += 1
            continue

        if not dry:
            write_file(path, name, due, posted, source,
                       ([context] if context else []) + ["Full spec on Harvey (not yet mirrored)."])
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
    dry = "--dry-run" in argv
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

        res = scan(code, cdir, cfm, m.group(0), columns, contents, dry)
        if not dry:
            write_manifest(cdir, columns, contents, res["links"])
        # the discussion rundown is dry-run only; the job summary stays terse
        for d in res["discussions"] if dry else []:
            if d["pair"]:
                state = ("pair on disk" if os.path.exists(d["initial_file"])
                         and os.path.exists(d["file"]) else "pair incomplete")
                lines.append(f'{code}: discussion "{d["name"]}" ({state}) → '
                             f'"{d["initial_title"]}" {d["initial"]}T23:59 in '
                             f'{os.path.basename(d["initial_file"])}; '
                             f'"{d["reply_title"]}" {d["due"]} in '
                             f'{os.path.basename(d["file"])}')
            else:
                state = "on disk" if os.path.exists(d["file"]) else "not filed"
                lines.append(f'{code}: discussion "{d["name"]}" ({state}) → '
                             f'{d["due"]} in {os.path.basename(d["file"])}')
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

    verb = " would be" if dry else ""
    head = "Blackboard scan: no changes" if not (new or updated or flagged) else (
        f"Blackboard scan:{verb} {new} new, {updated} due updates, {flagged} flagged")
    out = [head] + lines + failures
    if flagged:
        out.append(f"Review flags await a decision — see {REVIEW}")
    text = "\n".join(out) + "\n"
    if not dry:
        open(SUMMARY, "w").write(text)
    print(text, end="")

    if (new or updated) and not skip_todoist and not dry:
        subprocess.run([sys.executable, "scripts/todoist-sync.py"])
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
