#!/usr/bin/env python3
# tests for check.py. every case builds a throwaway repo in a temp dir and runs
# check.py against it, so the real tree is never touched.
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CHECK = HERE / "check.py"

CLASS_FM = {
    "code": "CS-2123",
    "name": "Data Structures",
    "schedule": '"MWF 10:00-10:50"',
    "starts": "2026-08-24",
    "ends": "2026-12-11",
    "granola_folder_id": '"example-folder-0001"',
}

LECTURE = """---
{id_field}
class: CS-2123
date: 2026-08-24
title: "Singly linked lists"
topics: [linked lists]
---

# CS-2123 lecture

nodes and pointers.

## Transcript

Dr. Example: a node holds a value and a pointer.
"""


def run_check(root):
    return subprocess.run([sys.executable, str(CHECK), str(root)],
                          capture_output=True, text=True)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "inbox").mkdir()
        self.cdir = self.root / "classes" / "cs-2123"
        shutil.copytree(REPO / "classes" / "_template", self.cdir)
        self.write_class(CLASS_FM)

    def tearDown(self):
        self.tmp.cleanup()

    def write_class(self, fm):
        # the template ships placeholders; fill in what check.py requires
        lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["---", "", "# CS-2123", ""]
        (self.cdir / "class.md").write_text("\n".join(lines))

    def lecture(self, name, id_field):
        (self.cdir / "lectures" / name).write_text(LECTURE.format(id_field=id_field))

    def test_template_class_is_clean(self):
        self.lecture("2026-08-24.md", "granola_id: example-0001")
        res = run_check(self.root)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("clean", res.stdout)

    def test_example_class_is_clean(self):
        # keeps examples/cs-2123 from rotting away from the linter
        shutil.rmtree(self.cdir)
        shutil.copytree(REPO / "examples" / "cs-2123", self.cdir)
        res = run_check(self.root)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("clean", res.stdout)

    def test_lecture_without_an_id_fails(self):
        self.lecture("2026-08-24.md", 'unrelated: ""')
        res = run_check(self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("granola_id or source_id", res.stdout)

    def test_lecture_with_both_ids_fails(self):
        self.lecture("2026-08-24.md", "granola_id: example-0001\nsource_id: 4f2a91c0be73")
        res = run_check(self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("keep exactly one", res.stdout)

    def test_source_id_alone_is_clean(self):
        self.lecture("2026-08-24.md", "source_id: 4f2a91c0be73")
        res = run_check(self.root)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_duplicate_id_fails(self):
        self.lecture("2026-08-24.md", "granola_id: example-0001")
        self.lecture("2026-08-24-2.md", "granola_id: example-0001")
        res = run_check(self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("duplicate lecture id", res.stdout)

    def test_duplicate_across_both_id_fields_fails(self):
        self.lecture("2026-08-24.md", "granola_id: 4f2a91c0be73")
        self.lecture("2026-08-24-2.md", "source_id: 4f2a91c0be73")
        res = run_check(self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("duplicate lecture id", res.stdout)

    def test_bad_discussion_weekday_fails(self):
        self.write_class(dict(CLASS_FM, discussion_initial_post="funday"))
        res = run_check(self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("is not a weekday name", res.stdout)

    def test_merge_conflict_marker_fails(self):
        self.lecture("2026-08-24.md", "granola_id: example-0001")
        path = self.cdir / "lectures" / "2026-08-24.md"
        path.write_text(path.read_text() + "<<<<<<< HEAD\nmine\n>>>>>>> theirs\n")
        res = run_check(self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("merge conflict marker", res.stdout)


if __name__ == "__main__":
    unittest.main()
