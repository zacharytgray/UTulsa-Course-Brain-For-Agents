---
name: digest
description: >
  Summarize the last week across all classes — what was covered in lecture, what's
  due soon, and what needs a look. Use when the user says "weekly digest", "what
  happened this week", "catch me up on classes", "what's due", or "school digest".
  Takes an optional number of days to look back.
---

# digest

A read-only weekly catch-up. Output goes to the chat — this skill never writes files.

## Steps

1. Window: the argument is the number of days back, default 7. Compute the start date from today.
2. Read every `classes/*/class.md` except `_template` for `code`, `name`, and `role`. Label `role: ta` classes as "(TA)" in the heading; their assignments show under "To grade", not "Due soon".
3. Lectures: glob `classes/*/lectures/*.md` and keep the ones whose filename date falls in the window.
   - **Read the frontmatter and the summary only. Stop at the `## Transcript` heading.** Transcripts are thousands of lines and will blow up context.
   - How: `grep -n '^## Transcript' <file>` to get the line number, then `Read` with `limit` set just under it. If the grep finds nothing, read the first 60 lines and note the file as suspect.
4. Assignments: read every `classes/*/assignments/*.md` frontmatter (skip `_template.md`). Keep those with `status: open` and either a `due` in the next 14 days or a `due` already past.
5. Write the digest to chat in the format below. Keep it under roughly 40 lines for a normal week — this is a scan, not a report.

## Output format

```markdown
# Week of <start> – <today>

## <CODE> — <Class Name>
- <what was covered, 2–4 bullets, synthesized across the week's lectures> (<date>)
- ...

## <next class>
...

## Due soon
- <YYYY-MM-DD> — [<CODE>] <title>  (overdue / in N days)
- ...

## Flags
- <thing that needs a human look>
```

- Bullets synthesize across lectures; they don't restate each summary one at a time. Cite the lecture date in parentheses so it's traceable.
- A class with no lectures in the window gets one line: `No lectures this week.`
- "Due soon" is across all classes, sorted by date, overdue items first and marked.

## Flags

Put these in the Flags section — they're the things that need a human, not automation:

- A deadline mentioned in a lecture summary (an exam date, a quiz, "homework due Friday") with no matching file in that class's `assignments/`. Quote the phrase and name the lecture date.
- A lecture whose summary is empty, very short, or garbled. That's a transcription-quality signal — worth knowing early in the semester.
- An assignment past due that's still `status: open`.

Skip the section entirely if there's nothing to flag.

## Scope rules

- Never read below `## Transcript` unless the user asks a specific question that the summaries can't answer.
- Never write, move, or edit files. No Todoist calls, no git. Reporting only.
- Don't invent an assignment file for a flagged deadline — flagging it is the whole job.
