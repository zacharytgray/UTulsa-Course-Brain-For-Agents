#!/usr/bin/env python3
# tests for blackboard-scan.py's scan(). everything runs in a temp repo, and
# bb_get is stubbed to blow up so a stray network call fails loudly.
import importlib.util
import os
import tempfile
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("blackboard_scan",
                                               os.path.join(HERE, "blackboard-scan.py"))
bbs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bbs)

CODE = "CS-2123"
CDIR = "classes/cs-2123"
CFM = {"code": CODE, "starts": "2026-08-24  # first day", "ends": "2026-12-11  # last day",
       "blackboard_url": "https://harvey.utulsa.edu/ultra/courses/_11111_1/outline"}
CID = "_11111_1"


def column(name, due=None, possible=100.0, cid=None):
    return {"id": f"_col_{bbs.slug(name)}", "effectiveColumnName": name, "name": None,
            "dueDate": due, "possible": possible, "contentId": cid or f"_c_{bbs.slug(name)}"}


def contents_for(columns, handler="resource/x-bb-assignment"):
    # every contentId resolves locally, so is_discussion never needs bb_get
    return [{"id": c["contentId"], "title": c["effectiveColumnName"], "parentId": None,
             "contentHandler": handler} for c in columns]


def scan(columns, dry=False, cfm=None, handler="resource/x-bb-assignment"):
    return bbs.scan(CODE, CDIR, cfm or CFM, CID, columns,
                    contents_for(columns, handler), dry)


def read(path):
    with open(path) as f:
        return f.read()


def headings():
    if not os.path.exists(bbs.REVIEW):
        return []
    return [ln for ln in read(bbs.REVIEW).splitlines() if ln.startswith("## ")]


def assignments():
    return sorted(f for f in os.listdir(f"{CDIR}/assignments") if f.endswith(".md"))


def put_manifest(columns):
    bbs.write_manifest(CDIR, columns, contents_for(columns), {})


def put_assignment(slug, title, due):
    path = f"{CDIR}/assignments/{slug}.md"
    with open(path, "w") as f:
        f.write(f'---\ntitle: "{title}"\ndue: {due}\nposted: \n'
                'source: ""\nstatus: open\ntodoist_task_id: ""\n---\n\nspec.\n')
    return path


class ScanTest(unittest.TestCase):
    def setUp(self):
        # the script writes with bare open(); don't drown the run in those
        warnings.simplefilter("ignore", ResourceWarning)
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.makedirs(os.path.join(self.tmp.name, CDIR, "assignments"))
        os.chdir(self.tmp.name)
        self.real_get = bbs.bb_get
        bbs.bb_get = self.no_network

    def tearDown(self):
        bbs.bb_get = self.real_get
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def no_network(self, path):
        raise AssertionError(f"scan tried to hit blackboard: {path}")

    def test_no_due_date_flags_once(self):
        col = column("Session #2 - Participation Points")
        res = scan([col])
        self.assertEqual(res["flagged"], 1)
        self.assertEqual(res["new"], 0)
        self.assertEqual(assignments(), [])
        self.assertEqual(len(headings()), 1)
        self.assertIn("Session #2 - Participation Points", headings()[0])
        self.assertIn("no due date", read(bbs.REVIEW))

        # second run with the column in the manifest: no repeat flag
        put_manifest([col])
        again = scan([col])
        self.assertEqual(again["flagged"], 0)
        self.assertEqual(len(headings()), 1)

    def test_participation_with_due_is_filed(self):
        res = scan([column("Session #2 - Participation Points",
                           due="2026-09-04T04:59:00.000Z")])
        self.assertEqual(res["new"], 1)
        self.assertEqual(assignments(), ["session-2-participation-points.md"])
        fm, _ = bbs.frontmatter(read(f"{CDIR}/assignments/session-2-participation-points.md"))
        self.assertEqual(fm["title"], "Session #2 - Participation Points")
        self.assertEqual(fm["due"], "2026-09-03T23:59")
        self.assertEqual(fm["status"], "open")
        self.assertEqual(headings(), [])

    def test_skip_is_whole_name_only(self):
        res = scan([column("Attendance"), column("Overall Grade"),
                    column("Session #5 - Attendance", due="2026-10-02T04:59:00.000Z")])
        self.assertEqual(res["new"], 1)
        self.assertEqual(res["flagged"], 0)
        self.assertEqual(assignments(), ["session-5-attendance.md"])
        # the bare columns never reached the flag path either
        self.assertFalse(os.path.exists(bbs.REVIEW))

    def test_zero_point_knowledge_check_is_filed(self):
        res = scan([column("Knowledge Check: Big-O", due="2026-09-07T04:59:00.000Z",
                           possible=0.0)])
        self.assertEqual(res["new"], 1)
        self.assertEqual(assignments(), ["knowledge-check-big-o.md"])
        fm, _ = bbs.frontmatter(read(f"{CDIR}/assignments/knowledge-check-big-o.md"))
        self.assertEqual(fm["title"], "Knowledge Check: Big-O")
        self.assertEqual(fm["due"], "2026-09-06T23:59")

    def test_moved_due_date_updates_existing_file(self):
        put_assignment("exam-1", "Exam 1", "2026-10-01T23:59")
        res = scan([column("Exam 1", due="2026-10-19T04:59:00.000Z")])
        self.assertEqual(res["updated"], 1)
        self.assertEqual(res["new"], 0)
        self.assertEqual(assignments(), ["exam-1.md"])
        fm, _ = bbs.frontmatter(read(f"{CDIR}/assignments/exam-1.md"))
        self.assertEqual(fm["due"], "2026-10-18T23:59")

    def test_discussion_files_one_file_by_default(self):
        # detected by contentHandler, not by a "Discussion:" title prefix
        res = scan([column("Module 2 Debate", due="2026-09-14T04:59:00.000Z")],
                   handler=bbs.FORUM)
        self.assertEqual(res["new"], 1)
        self.assertEqual(assignments(), ["module-2-debate.md"])
        fm, _ = bbs.frontmatter(read(f"{CDIR}/assignments/module-2-debate.md"))
        # a forum column's time is a creation stamp; the date's 23:59 is the deadline
        self.assertEqual(fm["due"], "2026-09-13T23:59")
        self.assertEqual(res["discussions"][0]["pair"], False)

    def test_discussion_pair_when_class_opts_in(self):
        cfm = dict(CFM, discussion_initial_post="friday  # initial post rule")
        res = scan([column("Module 2 Debate", due="2026-09-14T04:59:00.000Z")],
                   cfm=cfm, handler=bbs.FORUM)
        self.assertEqual(res["new"], 2)
        self.assertEqual(assignments(),
                         ["module-2-debate-initial-post.md", "module-2-debate.md"])
        reply, _ = bbs.frontmatter(read(f"{CDIR}/assignments/module-2-debate.md"))
        initial, _ = bbs.frontmatter(
            read(f"{CDIR}/assignments/module-2-debate-initial-post.md"))
        self.assertEqual(reply["title"], "Discussion Reply: Module 2 Debate")
        self.assertEqual(reply["due"], "2026-09-13T23:59")
        self.assertEqual(initial["title"], "Discussion: Module 2 Debate")
        self.assertEqual(initial["due"], "2026-09-11T23:59")

        # rerun: both halves exist, nothing new and no flag
        again = scan([column("Module 2 Debate", due="2026-09-14T04:59:00.000Z")],
                     cfm=cfm, handler=bbs.FORUM)
        self.assertEqual((again["new"], again["flagged"]), (0, 0))
        self.assertEqual(len(assignments()), 2)

    def test_dry_run_writes_nothing(self):
        put_assignment("exam-1", "Exam 1", "2026-10-01T23:59")
        res = scan([column("Session #2 - Participation Points"),
                    column("Knowledge Check: Big-O", due="2026-09-07T04:59:00.000Z",
                           possible=0.0),
                    column("Exam 1", due="2026-10-19T04:59:00.000Z")], dry=True)
        self.assertEqual((res["new"], res["updated"], res["flagged"]), (1, 1, 1))
        self.assertEqual(assignments(), ["exam-1.md"])
        self.assertFalse(os.path.exists(bbs.REVIEW))
        fm, _ = bbs.frontmatter(read(f"{CDIR}/assignments/exam-1.md"))
        self.assertEqual(fm["due"], "2026-10-01T23:59")
        self.assertFalse(os.path.exists(f"{CDIR}/.bb-manifest.json"))


if __name__ == "__main__":
    unittest.main()
