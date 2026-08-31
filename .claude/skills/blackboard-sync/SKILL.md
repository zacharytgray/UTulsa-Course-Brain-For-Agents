---
name: blackboard-sync
description: >
  Check a class's Blackboard page for new assignments and materials, and file
  them in the repo. Use when the user says "sync blackboard", "check blackboard
  for <class>", "pull new assignments", or "anything new posted". Takes an
  optional class code.
---

# blackboard-sync

Drive the browser to each class's Blackboard page, diff what's posted against what's in the repo, and file anything new.

The scheduled scan (`scripts/blackboard-scan.py`) already handles the gradebook-driven part on its own: new graded assignments get filed, and due dates that moved get fixed. This skill is for the rest — browsing content, downloads, and anything the scan flagged to `inbox/blackboard-review.md` because it wouldn't decide alone.

> Blackboard's layout varies by course and instructor. The navigation steps below are a starting procedure — adjust them once you've seen your real course pages, then update this file.

## Steps

1. Read every `classes/*/class.md` except `_template`. Keep the ones with a non-empty `blackboard_url`. If an argument was given, keep only that class code.
2. Try the API first — see [Harvey API map](#harvey-api-map-verified-2026-08-24) below for the endpoints and their shapes. Run `scripts/bb check` (Bash); if it says "no state" or "expired", run `scripts/bb login`. The memberships → contents → gradebook trio covers most of a sync, so use it before page-walking. Fall back to the browser for anything the JSON doesn't cover.
3. Open the class's `blackboard_url` with the browser tools (Claude in Chrome, or the in-app Browser).
   - If a login or SSO page appears, run `scripts/bb login` (Bash) and reload the page. The script signs in with the 1Password creds and TOTP itself. You still never type a username, password, or code by hand — only the script touches them. If the script fails, show its stderr and stop.
4. Once the course page loads, walk these areas (names vary — look for the closest equivalent in the course menu):
   - **Assignments** — or "Homework", "Coursework"
   - **Content** / **Course Materials** — or "Modules", "Weekly Content", "Lectures"
   - **Announcements** — read only, for context on due-date changes. Don't file announcements.
5. Build a list of posted items. For each: title, due date if shown, posted date if shown, the item's url, and any attachment filenames.
6. Diff against the repo:
   - assignments: compare against the `title:` frontmatter of every `classes/<class>/assignments/*.md` (skip `_template.md`), matched loosely (case, punctuation, "HW 1" vs "HW1")
   - materials: compare against the filenames already mirrored into the class's `workdir` under `harvey/`
   - Anything ambiguous goes in the report as "possible match — check", not filed as new.
7. For each genuinely new assignment, write `classes/<class>/assignments/<slug>.md` (kebab-case slug from the title):

```yaml
---
title: "<exact title from Blackboard>"
due: <ISO date or datetime, local time; leave empty if none shown>
posted: <ISO date if shown>
source: "<the item's url>"
status: open
todoist_task_id: ""
---
```

   Always double-quote `title` and `source` — titles like `HW #1` and urls with `#fragments` break unquoted. Body: the assignment description converted to markdown. Keep the professor's wording; don't summarize or improve it.

8. Attachments and downloads: run `scripts/blackboard-mirror.py <class-code>`. It walks the class's
   content tree, downloads every file to the class's `workdir` under
   `harvey/<blackboard folder path>/<original filename>`, and fills assignment spec text into
   `classes/<class>/assignments/*.md` where the `Full spec on Harvey (not yet mirrored).`
   placeholder sits. It tracks what it has already pulled in `classes/<class>/.bb-mirror.json`, so
   rerunning is safe. Use `--dry-run` first if you want to see what it would fetch. For a one-off
   file outside the mirror, `scripts/bb download <path> <dest>` fetches raw bytes — save it under
   the workdir's `materials/` or a `homework/` subfolder, never in `harvey/`. Nothing binary goes
   in this repo.
9. Report: new assignments filed, new materials mirrored, items skipped as already-present, ambiguous matches, and anything the page wouldn't show. Then suggest running `/assignment-sync` to push the new deadlines to Todoist.

## Harvey API map (verified 2026-08-24)

Harvey is TU's Blackboard Ultra, at `harvey.utulsa.edu`.

**Entry and auth.** The landing page has a "TU Single Sign-On (SSO)" button that hands off to
`login.microsoftonline.com` (Entra). A cookie/terms dialog shows up on the first visit. Scripted
path: `scripts/bb login`. The UI course list is at `/ultra/course` — check the Terms filter chip
shows the semester you want, it can default to the wrong one.

**Once a session exists**, the JSON API needs nothing but the session cookies. Send
`Accept: application/json`.

- `GET /learn/api/v1/users/me` — cheap session check.
- `GET /learn/api/v1/users/me/memberships?expand=course&limit=50` — every enrollment. Per course:
  `id` (e.g. `_12345_1`), `externalAccessUrl` (the `/ultra/courses/<id>/outline` url that goes in
  `blackboard_url`), `displayName`, `term.name` (e.g. `2026FA`), and `role` (`T` = TA/instructor,
  `S` = student).
- `GET /learn/api/v1/courses/<id>/contents?recursive=true&limit=200` — the full content tree. Items
  carry `id`, `parentId`, `title`, and `contentHandler` (`resource/x-bb-folder`, `-document`,
  `-file`, `-asmt-test-link`, `-courselink`, `-blti-link`, …). `body.rawText` is HTML and embeds
  attachments as `<a data-bbfile='{"displayName":...}' href="/bbcswebdav/pid-...">`; those
  `/bbcswebdav/...` urls download directly with the same cookies. Raise `limit` — 200 truncates a
  big course mid-tree.
- `GET /learn/api/v1/courses/<id>/gradebook/columns?limit=100` — graded items with
  `effectiveColumnName` (the `name` field is null on Harvey), `dueDate`, `possible` points, and
  `contentId`. This is the authoritative due-date source, better than anything on the content
  pages. An empty gradebook returns `results: []` — normal early in the semester.

**Gradebook gotchas.** `dueDate` is UTC — convert to America/Chicago (`04:59Z` in summer,
`05:59Z` in winter both mean 23:59 the previous local day). Dedupe columns by `name`: stale
duplicates with old dates hang around, so keep the one whose due date falls inside the semester.
Skip Attendance and Overall Grade — they aren't assignments. Knowledge Checks are
tracked only when `possible` > 0 (a few carry extra credit); zero-point ones are skipped.

**Discussion boards (verified 2026-08-27).** Harvey's discussions are classic
Original-view boards even though the course shell is Ultra — the JSON discussion endpoints
(`/learn/api/v1/courses/<id>/discussions/...`) answer `200 {}` with no error, which looks like
"no posts" but means "wrong API". The working chain:

1. Find the discussion in the content tree: a `resource/x-bb-courselink` item whose
   `contentDetail` gives a `linkSourceId`; fetch that content id and its
   `resource/x-bb-forumlink` detail carries the real `forum_id` (and `conferenceId`).
2. Read the board via the classic HTML/AJAX endpoints with `scripts/bb get <path> --html`:
   - `/webapps/discussionboard/do/forum?action=list_threads&course_id=<cid>&forum_id=<fid>&nav=discussion_board_entry` — thread list
   - `.../do/message?action=message_tree&course_id=<cid>&forum_id=<fid>&message_id=<thread root>` — all message ids, authors, nesting levels, timestamps
   - `.../do/message?action=message_frame&course_id=<cid>&forum_id=<fid>&message_id=<mid>` — one post's body HTML
   Plain cookie-carrying GETs are enough; no real browser needed. (`action=collect` needs
   POSTed ids — skip it.) Reading a post does bump its view counter; that's the only side effect.

**Caveat.** `scripts/bb get` wraps these once a state file exists. In the in-app Browser pane,
same-origin `fetch`/XHR *sometimes* works — but script-context requests can lose session cookies
and get routed to Blackboard's static S3 (XML `NoSuchKey` 404s) even while the user is logged in.
Top-level *navigations* always carry cookies, so the reliable pattern is: navigate the tab to the
API url and read the page text. For files, a plain `/bbcswebdav/` url triggers a save dialog the
agent can't accept; append `?isInlineRender=true&xythos-download=true&render=inline` (the
`viewerUrl`) to open Blackboard's doc viewer and extract the rendered text from the page (works
for PDFs — verified by capturing a syllabus this way).

## Scope rules

- Sign-in is scripted: `scripts/bb login` (1Password service account + TOTP). Claude never types credentials itself — if the script can't sign in, stop and report; don't fall back to manual credential entry.
- Never modify an existing assignment file, with two exceptions: filling an empty `source` with the url you just found, and the mirror script replacing a `Full spec on Harvey (not yet mirrored).` placeholder with the real spec. Not the due date, not the status, not the rest of the body — if Blackboard now shows a different due date, report it and let the user decide.
- Mirror everything by default. Every class's Blackboard content is kept locally so an agent helping with homework already has the slides and handouts.
- `scripts/blackboard-mirror.py [class-code] [--dry-run]` is the tool for it. Run it instead of downloading files one at a time; it's idempotent, so a rerun only picks up what's new.
- Files land in the class's `workdir` (class.md frontmatter) under `harvey/`, mirroring the Blackboard folder structure and keeping original filenames. Nothing binary goes in this repo. Text — specs, quiz and test question text, manifests — goes in the repo.
- `harvey/` is the script's folder alone. It's pruned to match Blackboard (only files the script itself downloaded — don't hand-place files there), and deleting the whole folder is harmless. Files that aren't on Blackboard go in the workdir's `materials/`. The sync never touches `materials/`, `homework/`, `exams/`, `projects/`, or `grading/`.
- Never accept course agreements, submit anything, or click a submission button. Reading and downloading only.
- Only touch the classes that have a `blackboard_url`. Skip the rest quietly.
