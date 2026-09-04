# Examples

`cs-2123/` is a synthetic class, filled in the way a real one looks after a few
weeks of syncing. Nothing in it is real: the professor, the email, the Blackboard
urls, the Granola id and the transcripts are all made up. Use it to see the shape
before you have any content of your own.

What is in it:

| file | what it shows |
| --- | --- |
| `class.md` | every frontmatter field a class needs, filled in |
| `syllabus.md` | the text-only syllabus that lives in the repo |
| `lectures/2026-08-24.md` | a Granola lecture: `granola_id`, summary, `## Transcript` |
| `lectures/2026-08-26.md` | the same file written by `scripts/lecture-import.py`, so it carries a `source_id` instead |
| `assignments/hw0-setup.md` | a finished assignment: `status: submitted` plus a `## Submitted` section |
| `assignments/hw1-linked-lists.md` | an open assignment with an empty `todoist_task_id`, waiting for a task sync |

`check.py` only lints `classes/`, so this folder is never checked as part of a
normal run. The test suite copies it into a temp tree and lints it there, which
is what keeps it honest.

## Trying it

Copy the class in and lint it:

```bash
cp -r examples/cs-2123 classes/cs-2123
python3 scripts/check.py
```

Then point an agent at the repo and ask it something that needs both files, like
"what did HW1 ask for, and which lecture covers deletion". Remove it with
`rm -rf classes/cs-2123` when you are done, before adding your own classes.

Importing a transcript the way `lectures/2026-08-26.md` was made:

```bash
python3 scripts/lecture-import.py CS-2123 transcript.txt --date 2026-08-26 \
  --title "Deletion and doubly linked lists"
```
