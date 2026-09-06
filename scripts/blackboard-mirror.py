#!/usr/bin/env python3
# mirror blackboard course content: files go to the class workdir under the
# mirror folder (harvey/ by default, CB_MIRROR_DIRNAME renames it), mirroring
# the blackboard folder tree; spec text goes back into the repo's assignment
# files. never logs in itself - scripts/bb owns the session. state lives in each
# class's .bb-mirror.json so a rerun only fetches what's new. the mirror folder
# is script-owned: anything in there that blackboard no longer has gets pruned.
# nothing outside it is ever touched.
import argparse
import difflib
import glob
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from datetime import date
from html.parser import HTMLParser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER = "Full spec on Harvey (not yet mirrored)."
BASE = os.environ.get("CB_BB_BASE", "https://harvey.utulsa.edu")
MIRROR_DIR = os.environ.get("CB_MIRROR_DIRNAME", "harvey")
REVIEW = "inbox/blackboard-review.md"

REVIEW_HEADER = """# Blackboard review

Flagged Blackboard changes that need a human decision. To process from anywhere: open
claude.ai/code on this repo (works from a phone) and say "process the blackboard
review file". Apply or reject each entry, delete handled entries, commit and push —
Todoist reconciles on the next scheduled sync run.
"""


def h(s):
    return hashlib.sha256((s or "").strip().encode()).hexdigest()[:16]


def frontmatter(text):
    parts = text.split("---")
    fm = dict(re.findall(r"(?m)^(\w+):\s*(.*)$", parts[1]))
    # drop trailing comments; the class template ships them on workdir and an
    # unedited one would otherwise read as a real path
    return ({k: re.sub(r"\s*#.*$", "", v).strip().strip('"') for k, v in fm.items()},
            "---".join(parts[2:]).strip())


def bb(args):
    r = subprocess.run([f"{REPO}/scripts/bb"] + args, capture_output=True, text=True,
                       timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "bb failed")
    return r.stdout


def bb_get(path):
    return json.loads(bb(["get", path, "--raw"]))


def bb_html(path):
    return bb(["get", path, "--html"])


def bb_head(path):
    try:
        return json.loads(bb(["head", path]))
    except Exception:
        return {}


# ultra assessments keep their instructions under contentDetail, not body
def spec_html(item):
    html = (item.get("body") or {}).get("rawText") or ""
    if html:
        return html
    test = ((item.get("contentDetail") or {}).get("resource/x-bb-asmt-test-link") or {}).get("test") or {}
    return ((test.get("assessment") or {}).get("instructions") or {}).get("rawText") or ""


def fetch_all(path):
    out = []
    while path:
        data = bb_get(path)
        out += data.get("results", [])
        path = (data.get("paging") or {}).get("nextPage")
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def sanitize(s):
    s = html.unescape(s or "")
    s = re.sub(r"[/:\\]", "-", s)
    s = re.sub(r"\s+", " ", s).strip().strip(".").strip()
    return s[:120] or "untitled"


# --- html -> markdown -------------------------------------------------------

def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", "", s))).strip()


def html_to_md(raw):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", raw or "")
    s = re.sub(r"(?is)<(strong|b)[^>]*>(.*?)</\1>", lambda m: "**" + strip_tags(m.group(2)) + "**", s)
    s = re.sub(r"(?is)<(em|i)[^>]*>(.*?)</\1>", lambda m: "*" + strip_tags(m.group(2)) + "*", s)
    s = re.sub(r'(?is)<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
               lambda m: f"[{strip_tags(m.group(2)) or m.group(1)}]({html.unescape(m.group(1))})", s)
    for n in range(1, 7):
        s = re.sub(rf"(?i)<h{n}\b[^>]*>", "\n\n" + "#" * n + " ", s)
        s = re.sub(rf"(?i)</h{n}\s*>", "\n\n", s)
    s = re.sub(r"(?i)<li\b[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|tr|ul|ol|li|table)\s*>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = html.unescape(s)
    s = "\n".join(l.rstrip() for l in s.splitlines())
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def squeeze(s):
    return re.sub(r"[ \t\xa0]+", " ", s).strip()


def bbfile_name(attr):
    # attached-file links are often icon-only, so the visible name lives here
    try:
        meta = json.loads(html.unescape(attr or ""))
    except ValueError:
        return ""
    return meta.get("displayName") or meta.get("linkName") or ""


class PageMarkdown(HTMLParser):
    # ultra page bodies are plain html: paragraphs wrapped in layout divs, spans
    # for colour, links, the odd list or table. html.parser keeps this stdlib -
    # the script has no third-party deps and shouldn't grow one for this.
    # html_to_md above stays as-is: it feeds assignment spec text, and retuning
    # it would churn every spec the mirror has already filled in.
    BLOCKS = ("p", "div", "section", "article", "blockquote",
              "h1", "h2", "h3", "h4", "h5", "h6")
    # a markdown cell is one line, so these only separate text inside one
    SEPS = BLOCKS + ("br", "hr", "pre", "ul", "ol", "li")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.buf, self.lists, self.links = [], [], [], []
        self.skip, self.indent = 0, ""
        self.table = self.row = self.cell = None

    def write(self, s):
        (self.cell if self.cell is not None else self.buf).append(s)

    def flush(self, blank=False):
        # indent is set by list items; squeeze would eat it off the front
        line = squeeze("".join(self.buf))
        self.buf, indent, self.indent = [], self.indent, ""
        if line:
            self.lines.append(indent + line)
        if blank and self.lines and self.lines[-1]:
            self.lines.append("")

    def close_row(self):
        if self.row and any(self.row):
            self.table.append(self.row)
        self.row = None

    def emit_table(self, rows):
        if len(rows) == 1 and len(rows[0]) == 1:
            self.lines += [rows[0][0], ""]  # a one-cell table is layout, not data
            return
        wide = max(len(r) for r in rows)
        rows = [r + [""] * (wide - len(r)) for r in rows]
        self.lines += ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * wide]
        self.lines += ["| " + " | ".join(r) + " |" for r in rows[1:]] + [""]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        elif self.skip:
            return
        elif self.cell is not None and tag in self.SEPS:
            self.write(" ")
        elif tag == "br":
            self.flush()
        elif tag == "hr":
            self.flush(True)
            self.lines += ["---", ""]
        elif tag == "pre":
            # ultra uses these for one-line shell commands, not code blocks
            self.flush(True)
            self.write("`")
        elif tag == "table":
            self.flush(True)
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.close_row()  # editors leave </tr> off often enough
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag in ("ul", "ol"):
            self.flush(not self.lists)
            self.lists.append([tag, 0])
        elif tag == "li":
            self.flush()
            kind, n = self.lists[-1] if self.lists else ["ul", 0]
            if self.lists:
                self.lists[-1][1] = n = n + 1
            self.indent = "  " * max(len(self.lists) - 1, 0)
            self.write(f"{n}. " if kind == "ol" else "- ")
        elif tag in ("strong", "b"):
            self.write("**")
        elif tag in ("em", "i"):
            self.write("*")
        elif tag == "a" and a.get("href"):
            target = self.cell if self.cell is not None else self.buf
            self.links.append((a["href"], bbfile_name(a.get("data-bbfile")), target, len(target)))
        elif tag in self.BLOCKS:
            self.flush(True)
            if tag[0] == "h" and tag[1:].isdigit():
                self.write("#" * int(tag[1:]) + " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(self.skip - 1, 0)
        elif self.skip:
            return
        elif self.cell is not None and tag in self.SEPS:
            self.write(" ")
        elif tag in ("td", "th") and self.cell is not None:
            self.row.append(squeeze("".join(self.cell)).replace("|", r"\|"))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.close_row()
        elif tag == "table" and self.table is not None:
            self.close_row()
            if self.table:
                self.emit_table(self.table)
            self.table = None
        elif tag == "pre":
            self.write("`")
            self.flush(True)
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self.flush(not self.lists)
        elif tag == "li":
            self.flush()
        elif tag in ("strong", "b"):
            self.write("**")
        elif tag in ("em", "i"):
            self.write("*")
        elif tag == "a" and self.links:
            href, name, target, at = self.links.pop()
            text = squeeze("".join(target[at:])) or name
            del target[at:]
            href = html.unescape(href)
            target.append(f"[{text or href}]({BASE + href if href.startswith('/') else href})")
        elif tag in self.BLOCKS:
            self.flush(True)

    def handle_data(self, data):
        if not self.skip:
            self.write(data)

    def markdown(self):
        self.close()
        self.flush()
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self.lines)).strip()


def page_md(raw):
    p = PageMarkdown()
    p.feed(raw or "")
    return p.markdown()


# --- content tree -----------------------------------------------------------

FOLDERS = ("resource/x-bb-folder", "resource/x-bb-lesson")


class Anchors(HTMLParser):
    # every <a> in a body, with its visible text. a regex can't do this: the
    # alt text inside data-bbfile carries raw ">" and cuts the tag match short.
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.attrs, self.text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.end_a()
            self.attrs, self.text = dict(attrs), []

    def handle_data(self, data):
        if self.attrs is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self.end_a()

    def end_a(self):
        if self.attrs is not None:
            self.out.append((self.attrs, squeeze("".join(self.text))))
            self.attrs = None


def anchors(raw):
    p = Anchors()
    p.feed(raw or "")
    p.close()
    p.end_a()
    return p.out


def filelink(url):
    # course files all live under /bbcswebdav/. the editor's scratch uploads
    # (/sessions/...) 403 for students, and /ultra/... links are pages
    url = (url or "").replace(BASE, "")
    return url if url.startswith("/bbcswebdav/") else ""


def folder_path(items, item):
    parts, node, seen = [], items.get(item.get("parentId")), set()
    while node and node["id"] not in seen:
        seen.add(node["id"])
        if node.get("contentHandler") in FOLDERS:
            parts.append(sanitize(node.get("title")))
        node = items.get(node.get("parentId"))
    return list(reversed(parts))


def bbfile_links(item):
    # every file a page links, not just the ones the editor tagged. deduped by
    # url, so an anchor carrying both a resourceUrl and an href counts once
    out, seen = [], set()
    for a, text in anchors((item.get("body") or {}).get("rawText") or ""):
        try:
            meta = json.loads(a.get("data-bbfile") or "")
        except ValueError:
            meta = {}
        # the href is what a student clicks, so it always works. resourceUrl is
        # a hint that often points at a scratch upload or a pre-import copy
        url = filelink(a.get("href")) or filelink(meta.get("resourceUrl"))
        if not url or url in seen:
            continue
        seen.add(url)
        name = meta.get("displayName") or meta.get("linkName") or text or os.path.basename(url)
        # display names and link text often drop the extension the file has,
        # and drive renames an extensionless file out from under the manifest.
        # splitext isn't enough on its own - a real extension is short
        if not re.fullmatch(r"\.\w{1,5}", os.path.splitext(name)[1]):
            name = name.rstrip(". ") + os.path.splitext(
                meta.get("fileName") or os.path.basename(url))[1]
        out.append((sanitize(name), url, meta.get("fileSize")))
    return out


def attached_files(cid, item):
    # /learn/api/v1/.../attachments answers {} (wrong api). the public route
    # works for x-bb-file but 400s on x-bb-document ("does not support file
    # attachments") - documents carry their files as data-bbfile links instead.
    # x-bb-file already has the file inline, so the request is only a fallback.
    detail = (item.get("contentDetail") or {}).get("resource/x-bb-file") or {}
    f = detail.get("file") or {}
    if f.get("permanentUrl") and f.get("fileName"):
        return [(sanitize(f["fileName"]), f["permanentUrl"], f.get("fileSize"))]
    out = []
    try:
        atts = fetch_all(f"/learn/api/public/v1/courses/{cid}/contents/{item['id']}/attachments")
    except Exception:
        return out
    for a in atts:
        if a.get("id") and a.get("fileName"):
            out.append((sanitize(a["fileName"]),
                        f"/learn/api/public/v1/courses/{cid}/contents/{item['id']}"
                        f"/attachments/{a['id']}/download", None))
    return out


def plan(cid, items):
    # (key, relative path under the mirror folder, url, remote size or None)
    out, taken = [], set()
    for item in sorted(items.values(), key=lambda i: i["id"]):
        found = bbfile_links(item)
        if item.get("contentHandler") == "resource/x-bb-file":
            seen = {n for n, _, _ in found}
            found += [f for f in attached_files(cid, item) if f[0] not in seen]
        dirparts = folder_path(items, item)
        for name, url, size in found:
            rel = os.path.join(*dirparts, name) if dirparts else name
            stem, ext = os.path.splitext(rel)
            n = 2
            while rel in taken:
                rel, n = f"{stem}-{n}{ext}", n + 1
            taken.add(rel)
            out.append((f"{item['id']}::{name}", rel, url, size))
    return out


def plan_pages(items, taken):
    # an ultra page keeps its html in a child item titled ultraDocumentBody, so
    # the parent folder is the page: it names the file and holds it. these have
    # no file to download - without this the text only exists on blackboard.
    # taken carries plan()'s paths so a page can't land on a downloaded file.
    # (key, relative path under the mirror folder, file contents)
    out, taken = [], set(taken)
    for item in sorted(items.values(), key=lambda i: i["id"]):
        if item.get("title") != "ultraDocumentBody":
            continue
        md = page_md((item.get("body") or {}).get("rawText") or "")
        if not md:
            continue
        title = html.unescape((items.get(item.get("parentId")) or {}).get("title") or "Page")
        dirparts = folder_path(items, item)
        rel = sanitize(title) + ".md"
        rel = os.path.join(*dirparts, rel) if dirparts else rel
        stem, n = rel[:-3], 2
        while rel in taken:
            rel, n = f"{stem}-{n}.md", n + 1
        taken.add(rel)
        out.append((f"page::{item['id']}", rel,
                    f"<!-- mirrored from blackboard item {item['id']}; "
                    f"{MIRROR_DIR}/ is script-owned, edits here get overwritten -->\n\n"
                    f"# {title}\n\n{md}\n"))
    return out


# --- assignment specs -------------------------------------------------------

def match_content(cid, items, columns, title, cache):
    # assignment file -> gradebook column (that's the only link the repo keeps)
    # -> contentId. discussion content ids aren't in the ultra tree, so fetch
    # those directly - cache hits and misses so a run asks at most once per id.
    n = norm(title)
    if not n:
        return []
    hits = [c for c in columns if norm(c["name"]) == n]
    if not hits:
        hits = [c for c in columns if norm(c["name"]) in n or n in norm(c["name"])]
    if not hits:
        hits = [{"contentId": i["id"]} for i in items.values() if norm(i.get("title") or "") == n]
    out = []
    for hit in hits:
        i = hit.get("contentId")
        if not i or i in [o.get("id") for o in out]:
            continue
        if i in items:
            out.append(items[i])
            continue
        if i not in cache:
            try:
                cache[i] = bb_get(f"/learn/api/v1/courses/{cid}/contents/{i}")
            except Exception:
                cache[i] = None
        if cache[i]:
            out.append(cache[i])
    return out


# the spec body is everything between the frontmatter and these sections; they
# are the user's (or mirror_tests') and never get rewritten
SECTION = re.compile(r"(?m)^## (?:Submitted|Questions)\b")


def split_spec(text):
    parts = text.split("---")
    head = "---" + parts[1] + "---"
    rest = "---".join(parts[2:])
    m = SECTION.search(rest)
    cut = m.start() if m else len(rest)
    return head, rest[:cut], rest[cut:]


def rejoin(head, region, tail):
    out = head + "\n\n" + region.strip() + "\n"
    return out + ("\n" + tail.lstrip("\n") if tail.strip() else "")


def add_spec_review(code, name, path, old, new):
    if not os.path.exists(REVIEW):
        os.makedirs("inbox", exist_ok=True)
        open(REVIEW, "w").write(REVIEW_HEADER)
    diff = "\n".join(list(difflib.unified_diff(
        (old or "").splitlines(), new.splitlines(),
        fromfile="repo", tofile=MIRROR_DIR, lineterm=""))[:60])
    # a spec with its own code fence (or a cut mid-fence) would leave ours open
    diff, new = re.sub(r"`{3,}", "`", diff), re.sub(r"`{3,}", "`", new)
    lines = [f'\n## {date.today().isoformat()} — {code}: "{name}" spec changed on Harvey', "",
             "Harvey's spec text for this assignment changed, but the file's body isn't what "
             "the mirror last generated — it was hand-edited, or written before the mirror "
             "tracked it. The file was left alone.", "",
             f"- `{path}`", ""]
    if diff:
        lines += ["Repo body vs Harvey's current text:", "", "```diff", diff, "```", ""]
    else:
        lines += ["Harvey's current text:", "", "```", new[:2000], "```", ""]
    lines.append("Options: replace the file's spec body with Harvey's text, or keep what's "
                 "there if the change doesn't matter.")
    with open(REVIEW, "a") as f:
        f.write("\n".join(lines) + "\n")


def sync_specs(code, cid, cdir, items, columns, manifest, seen_items, cache, dry):
    # fills placeholders, and on later runs re-pulls a spec whose upstream text
    # moved - but only when the file still reads as what we generated
    specs = manifest.setdefault("specs", {})
    filled, empty, updated, flagged = [], [], [], []
    for f in sorted(glob.glob(f"{cdir}/assignments/*.md")):
        if f.endswith("_template.md"):
            continue
        text = open(f).read()
        fm, _ = frontmatter(text)
        item, spec = None, ""
        for cand in match_content(cid, items, columns, fm.get("title", ""), cache):
            spec = html_to_md(spec_html(cand))
            if spec:
                item = cand
                break
        if not spec:
            if PLACEHOLDER in text:
                empty.append(os.path.basename(f))
            continue

        rel = os.path.relpath(f, REPO)
        head, region, tail = split_spec(text)
        base = os.path.basename(f)

        if PLACEHOLDER in text:
            prefix = region.split(PLACEHOLDER)[0]
            new = prefix + spec
            filled.append(base)
            if not dry:
                open(f, "w").write(rejoin(head, new, tail))
                # keep the prefix's own trailing blank lines; stripping them
                # would glue the context line onto the spec on a later rewrite
                specs[rel] = {"item": item["id"], "prefix": prefix.lstrip("\n"), "hash": h(new)}
            continue

        raw_hash = h(spec_html(item))
        was = (seen_items.get(item["id"]) or {}).get("raw_hash")
        rec = specs.get(rel)
        if was is None or was == raw_hash:
            # first sight of this item, or upstream text is unchanged. claim the
            # file if it still ends in the text we'd generate, so a later edit
            # can be applied instead of flagged
            if not rec and not dry and region.strip().endswith(spec.strip()):
                prefix = region.strip()[:len(region.strip()) - len(spec.strip())]
                specs[rel] = {"item": item["id"], "prefix": prefix, "hash": h(region)}
            continue

        pre = (rec or {}).get("prefix") or ""
        if rec and rec.get("hash") == h(region):
            new = pre + spec
            updated.append(base)
            if not dry:
                open(f, "w").write(rejoin(head, new, tail))
                specs[rel] = {"item": item["id"], "prefix": pre, "hash": h(new)}
            continue

        flagged.append(base)
        if not dry:
            # keep the context line out of the diff when we know we put it there
            add_spec_review(code, fm.get("title", base), rel, region.strip(), pre + spec)
    return filled, empty, updated, flagged


def test_questions(cid, item_id):
    # deployed tests normally need an attempt; the classic content page is the
    # only read-only surface worth a try.
    try:
        page = bb_html(f"/webapps/blackboard/content/listContent.jsp"
                       f"?course_id={cid}&content_id={item_id}")
    except Exception:
        return []
    if "questionContent" not in page and "questionText" not in page:
        return []
    qs = re.findall(r'(?is)<div[^>]*class="[^"]*question(?:Text|Content)[^"]*"[^>]*>(.*?)</div>', page)
    return [q for q in (html_to_md(x) for x in qs) if q]


def mirror_tests(cdir, cid, items, manifest, dry):
    known = manifest.setdefault("tests", {})
    mirrored, blocked = [], []
    for item in items.values():
        if item.get("contentHandler") != "resource/x-bb-asmt-test-link":
            continue
        prev = known.get(item["id"])
        if prev and prev.get("status") == "mirrored":
            mirrored.append(item.get("title"))
            continue  # already appended once; don't stack another ## Questions
        if prev and prev.get("status") == "inaccessible":
            blocked.append(item.get("title"))
            continue
        qs = test_questions(cid, item["id"])
        if not qs:
            blocked.append(item.get("title"))
            if not dry:
                known[item["id"]] = {"status": "inaccessible", "checked_at": date.today().isoformat()}
            continue
        hit = [f for f in glob.glob(f"{cdir}/assignments/*.md")
               if not f.endswith("_template.md")
               and norm(frontmatter(open(f).read())[0].get("title", "")) == norm(item.get("title") or "")]
        if not hit:
            blocked.append(item.get("title"))
            continue
        mirrored.append(item.get("title"))
        if not dry:
            with open(hit[0], "a") as fh:
                fh.write("\n## Questions\n\n" + "\n\n".join(qs) + "\n")
            known[item["id"]] = {"status": "mirrored", "checked_at": date.today().isoformat()}
    return mirrored, blocked


# --- run --------------------------------------------------------------------

def save(path, manifest):
    open(path, "w").write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def prune(root, files, keep, dry):
    # the mirror folder is script-owned, so anything we put there that blackboard dropped
    # goes too. only manifest entries - nothing else under the workdir is ours.
    gone = [k for k in files if k not in keep]
    for k in gone:
        dest = os.path.join(root, files[k]["path"])
        if dry:
            print(f"  - {files[k]['path']}")
            continue
        if os.path.exists(dest):
            os.remove(dest)
        del files[k]
    if not dry:
        for d, _, _ in sorted(os.walk(root), reverse=True):
            if d != root and not os.listdir(d):
                os.rmdir(d)
    return len(gone)


def run_class(code, cdir, cfm, dry):
    cid = re.search(r"_\d+_1", cfm.get("blackboard_url", "")).group(0)
    workdir = cfm.get("workdir", "")
    root = os.path.join(workdir, MIRROR_DIR)
    items = {i["id"]: i for i in
             fetch_all(f"/learn/api/v1/courses/{cid}/contents?recursive=true&limit=200")}
    columns = [{"name": c.get("effectiveColumnName") or c.get("name") or "",
                "contentId": c.get("contentId")}
               for c in fetch_all(f"/learn/api/v1/courses/{cid}/gradebook/columns?limit=200")]
    columns = [c for c in columns if c["name"]]

    mpath = f"{cdir}/.bb-mirror.json"
    manifest = json.load(open(mpath)) if os.path.exists(mpath) else {}
    files = manifest.setdefault("files", {})
    dead = manifest.setdefault("dead", {})
    # last run's per-item modified stamp + rawText hash. empty on the first run
    # after this feature landed, which is what keeps the backfill silent
    seen_items = manifest.get("items", {})

    got = skipped = failed = ndead = 0
    nbytes = 0
    errors = []
    wanted = plan(cid, items)
    for key, rel, url, remote in wanted:
        dest = os.path.join(root, rel)
        prev = files.get(key)
        iid = key.split("::")[0]
        was = seen_items.get(iid) or {}
        # the item's modifiedDate bumps whenever the instructor edits it, a
        # swapped file included. no stored stamp = first run with this field, so
        # don't read that as a change
        touched = (was.get("modified") is not None
                   and was["modified"] != (items.get(iid) or {}).get("modifiedDate"))
        # blackboard still lists these but the file is gone; asking again every
        # run just burns requests and buries a real failure. an edit to the item
        # is worth one more try - the instructor may have re-uploaded
        if dead.get(key, {}).get("url") == url and not touched:
            ndead += 1
            continue
        # fallback for the case the item stamp can't cover: no modifiedDate and
        # no size from blackboard, so ask the server for an etag. every item in
        # the ultra tree does carry a stamp, so this normally never fires -
        # probing on size alone costs one extra request per file, every run
        stamped = (items.get(iid) or {}).get("modifiedDate") is not None
        probe = bb_head(url) if (prev and remote is None and not stamped) else {}
        tag = probe.get("etag") or probe.get("modified")
        swapped = bool(tag and prev and prev.get("remote_tag") and tag != prev["remote_tag"])
        # compare remote size against what it was when we mirrored, not against
        # the local byte count - blackboard's reported size and the transferred
        # bytes don't always agree
        fresh = (prev and prev.get("path") == rel and prev.get("url", url) == url
                 and os.path.exists(dest) and os.path.getsize(dest) == prev.get("bytes")
                 and remote == prev.get("remote_bytes")
                 and not touched and not swapped)
        if fresh:
            if not dry:  # baseline for the next run
                prev["url"] = url
                if tag:
                    prev["remote_tag"] = tag
            skipped += 1
            continue
        if prev and prev.get("path") != rel:
            old = os.path.join(root, prev["path"])
            if not dry and os.path.exists(old):
                os.remove(old)  # moved in blackboard's tree
        if dry:
            print(f"  + {rel}")
            got += 1
            continue
        try:
            out = bb(["download", url, dest]).strip().rsplit(" ", 1)
            size = int(out[-1])
        except Exception as e:
            m = re.search(r"download failed(?: after login)?: (\d+)", str(e))
            status = int(m.group(1)) if m else 0
            if 400 <= status < 500:  # gone for good, not a blip - remember it
                ndead += 1
                errors.append(f"{rel}: dead link ({status})")
                if not dry:
                    dead[key] = {"url": url, "status": status,
                                 "checked_at": date.today().isoformat()}
                continue
            failed += 1
            errors.append(f"{rel}: {e}")
            continue
        dead.pop(key, None)  # a retry that worked; stop calling it dead
        files[key] = {"path": rel, "url": url, "bytes": size, "remote_bytes": remote,
                      "mirrored_at": date.today().isoformat()}
        if tag:
            files[key]["remote_tag"] = tag
        got += 1
        nbytes += size
        if got % 20 == 0:
            save(mpath, manifest)  # flush so a killed run resumes where it stopped

    # ultra page bodies: rendered from the item's html, otherwise managed like a
    # download - same manifest, same pruning, same skip-when-unchanged
    wrote = pskipped = 0
    pages = plan_pages(items, [rel for _, rel, _, _ in wanted])
    for key, rel, text in pages:
        dest = os.path.join(root, rel)
        prev = files.get(key)
        if (prev and prev.get("path") == rel and prev.get("hash") == h(text)
                and os.path.exists(dest) and os.path.getsize(dest) == prev.get("bytes")):
            pskipped += 1
            continue
        if dry:
            print(f"  + {rel}")
            wrote += 1
            continue
        if prev and prev.get("path") != rel:
            old = os.path.join(root, prev["path"])
            if os.path.exists(old):
                os.remove(old)  # renamed or moved in blackboard's tree
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "w").write(text)
        files[key] = {"path": rel, "page": True, "hash": h(text),
                      "bytes": os.path.getsize(dest),
                      "mirrored_at": date.today().isoformat()}
        wrote += 1

    keep = {k for k, _, _, _ in wanted} | {k for k, _, _ in pages}
    if not items and files:
        # an empty tree on a live session is blackboard glitching, not the
        # course being emptied - pruning here would wipe the whole mirror
        pruned = 0
        print(f"{code}: empty content tree, {len(files)} files already mirrored - skipping prune",
              file=sys.stderr)
    else:
        pruned = prune(root, files, keep, dry)
        for k in [k for k in dead if k not in keep]:
            if not dry:
                del dead[k]  # blackboard dropped the link too

    offtree = {}
    filled, unfilled, respecced, flagged = sync_specs(
        code, cid, cdir, items, columns, manifest, seen_items, offtree, dry)
    mirrored, blocked = mirror_tests(cdir, cid, items, manifest, dry)

    if items and not dry:
        # rewritten wholesale each run; an item blackboard dropped is just gone.
        # discussions live outside the tree, so fold in whatever sync_specs had
        # to fetch by id - otherwise their spec text is never seen to change
        seen = list(items.values()) + [i for i in offtree.values() if i]
        manifest["items"] = {
            i["id"]: {"modified": i.get("modifiedDate"),
                      "raw_hash": h(spec_html(i))}
            for i in seen}
    if not dry:
        save(mpath, manifest)

    print(f"{code}: {got} downloaded, {skipped} skipped, {pruned} pruned, {failed} failed, "
          f"dead links: {ndead}, {nbytes / 1e6:.1f} MB; "
          f"pages {wrote} written / {pskipped} skipped; "
          f"specs {len(filled)} filled / {len(respecced)} updated / {len(flagged)} flagged "
          f"/ {len(unfilled)} no text; "
          f"tests {len(mirrored)} mirrored / {len(blocked)} inaccessible")
    if flagged:
        print(f"  spec changes need a decision — see {REVIEW}")
    for e in errors[:10]:
        print(f"  ! {e}")
    return failed


def main():
    os.chdir(REPO)
    p = argparse.ArgumentParser()
    p.add_argument("code", nargs="?")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    bad = 0
    for cls_md in sorted(glob.glob("classes/*/class.md")):
        cdir = os.path.dirname(cls_md)
        if cdir.endswith("_template"):
            continue
        cfm, _ = frontmatter(open(cls_md).read())
        code = cfm.get("code", "")
        if not cfm.get("blackboard_url") or not cfm.get("workdir"):
            continue
        if a.code and code.lower() != a.code.lower():
            continue
        if not re.search(r"_\d+_1", cfm["blackboard_url"]):
            continue
        try:
            bad += run_class(code, cdir, cfm, a.dry_run)
        except Exception as e:
            print(f"{code}: failed: {e}", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
