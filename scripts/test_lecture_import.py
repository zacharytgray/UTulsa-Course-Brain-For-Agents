#!/usr/bin/env python3
# tests for lecture-import.py. runs it as a subprocess against a temp tree via
# CB_REPO_ROOT, so nothing lands in the real repo.
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPORTER = HERE / "lecture-import.py"

CLASS_MD = """---
code: CS-2123
name: Data Structures
schedule: "MWF 10:00-10:50"
starts: 2026-08-24
---

# CS-2123
"""

TRANSCRIPT = "Dr. Example: a node holds a value and a pointer to the next node.\n"


def frontmatter(text):
    out = {}
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            break
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


class LectureImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cdir = self.root / "classes" / "cs-2123"
        (self.cdir / "lectures").mkdir(parents=True)
        (self.cdir / "class.md").write_text(CLASS_MD)
        self.transcript = self.root / "transcript.txt"
        self.transcript.write_text(TRANSCRIPT)

    def tearDown(self):
        self.tmp.cleanup()

    def run_import(self, *args, transcript=None, code="CS-2123"):
        env = dict(os.environ, CB_REPO_ROOT=str(self.root))
        return subprocess.run(
            [sys.executable, str(IMPORTER), code, str(transcript or self.transcript),
             *args], capture_output=True, text=True, env=env)

    def lectures(self):
        return sorted(p.name for p in (self.cdir / "lectures").glob("*.md"))

    def test_writes_a_lecture_file(self):
        res = self.run_import("--date", "2026-08-26", "--title", "Deletion")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.lectures(), ["2026-08-26.md"])
        text = (self.cdir / "lectures" / "2026-08-26.md").read_text()
        fm = frontmatter(text)
        self.assertEqual(fm["class"], "CS-2123")
        self.assertEqual(fm["date"], "2026-08-26")
        self.assertEqual(fm["title"], "Deletion")
        self.assertEqual(fm["topics"], "[]")
        self.assertEqual(len(fm["source_id"]), 12)
        self.assertNotIn("granola_id", fm)
        self.assertIn("## Transcript", text)
        self.assertIn(TRANSCRIPT.strip(), text)
        # no summary given, so the file says so instead of pretending
        self.assertIn("Summary not written yet", text)

    def test_default_title_and_given_summary(self):
        summary = self.root / "summary.md"
        summary.write_text("Deleting from a singly linked list.\n")
        res = self.run_import("--date", "2026-08-26", "--summary", str(summary))
        self.assertEqual(res.returncode, 0, res.stderr)
        text = (self.cdir / "lectures" / "2026-08-26.md").read_text()
        self.assertEqual(frontmatter(text)["title"], "CS-2123 lecture 2026-08-26")
        self.assertIn("Deleting from a singly linked list.", text)
        self.assertNotIn("Summary not written yet", text)

    def test_second_run_is_a_noop(self):
        self.run_import("--date", "2026-08-26")
        res = self.run_import("--date", "2026-08-26")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("already filed", res.stdout)
        self.assertEqual(self.lectures(), ["2026-08-26.md"])

    def test_explicit_id_is_what_dedupes(self):
        self.run_import("--date", "2026-08-26", "--id", "whisper-0007")
        other = self.root / "other.txt"
        other.write_text("different words entirely.\n")
        res = self.run_import("--date", "2026-08-26", "--id", "whisper-0007",
                              transcript=other)
        self.assertIn("already filed", res.stdout)
        self.assertEqual(self.lectures(), ["2026-08-26.md"])

    def test_same_date_different_id_gets_a_suffix(self):
        self.run_import("--date", "2026-08-26")
        other = self.root / "other.txt"
        other.write_text("second meeting of the day.\n")
        res = self.run_import("--date", "2026-08-26", transcript=other)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.lectures(), ["2026-08-26-2.md", "2026-08-26.md"])
        self.assertIn("second meeting of the day.",
                      (self.cdir / "lectures" / "2026-08-26-2.md").read_text())

    def test_unknown_class_is_refused(self):
        res = self.run_import("--date", "2026-08-26", code="CS-9999")
        self.assertEqual(res.returncode, 1)
        self.assertIn("no class.md", res.stderr)
        self.assertEqual(self.lectures(), [])

    def test_bad_date_is_refused(self):
        res = self.run_import("--date", "Aug 26")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.lectures(), [])


if __name__ == "__main__":
    unittest.main()
