#!/usr/bin/env python3
# tests for gen-schedule.py's entries(): schedule parsing and the "30 min after
# the class ends" math. CB_REPO_ROOT points it at a temp class tree, and nothing
# here touches launchd.
import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

HERE = Path(__file__).resolve().parent
# weekday refresh runs, always there whatever the classes say
REFRESH = {(1, 7, 5), (2, 7, 5), (3, 7, 5), (4, 7, 5), (5, 7, 5)}


def load(root):
    # module-level REPO reads the env, so load a fresh copy per temp tree
    os.environ["CB_REPO_ROOT"] = str(root)
    spec = importlib.util.spec_from_file_location("gen_schedule",
                                                  HERE / "gen-schedule.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EntriesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "classes").mkdir()
        self.old_root = os.environ.get("CB_REPO_ROOT")

    def tearDown(self):
        if self.old_root is None:
            os.environ.pop("CB_REPO_ROOT", None)
        else:
            os.environ["CB_REPO_ROOT"] = self.old_root
        self.tmp.cleanup()

    def add_class(self, name, schedule, ends="2099-12-11"):
        d = self.root / "classes" / name
        d.mkdir()
        (d / "class.md").write_text(
            f'---\ncode: {name.upper()}\nname: Example\nschedule: "{schedule}"\n'
            f"starts: 2026-08-24\nends: {ends}\n---\n\n# {name.upper()}\n")

    def entries(self):
        err = io.StringIO()
        with redirect_stderr(err):
            out = load(self.root).entries()
        return set(out), err.getvalue()

    def test_bare_tree_is_just_the_refresh_runs(self):
        got, _ = self.entries()
        self.assertEqual(got, REFRESH)

    def test_end_time_plus_thirty(self):
        self.add_class("cs-2123", "MWF 10:00-10:50")
        got, _ = self.entries()
        self.assertEqual(got - REFRESH, {(1, 11, 20), (3, 11, 20), (5, 11, 20)})

    def test_multiple_segments_and_thursday(self):
        self.add_class("cs-2123", "TR 09:30-10:45, F 13:00-13:50")
        got, _ = self.entries()
        self.assertEqual(got - REFRESH, {(2, 11, 15), (4, 11, 15), (5, 14, 20)})

    def test_minute_rollover_keeps_the_hour_honest(self):
        self.add_class("cs-2123", "M 14:00-14:45")
        got, _ = self.entries()
        self.assertEqual(got - REFRESH, {(1, 15, 15)})

    def test_late_class_clamps_instead_of_rolling_past_midnight(self):
        self.add_class("cs-2123", "W 22:00-23:45")
        got, err = self.entries()
        self.assertEqual(got - REFRESH, {(3, 23, 59)})
        self.assertIn("rolls past midnight", err)

    def test_unparseable_segment_warns_and_is_skipped(self):
        self.add_class("cs-2123", "Mondays at ten")
        got, err = self.entries()
        self.assertEqual(got, REFRESH)
        self.assertIn("can't parse", err)

    def test_ended_class_is_skipped(self):
        self.add_class("cs-2123", "MWF 10:00-10:50", ends="2020-12-11")
        got, err = self.entries()
        self.assertEqual(got, REFRESH)
        self.assertIn("ended 2020-12-11", err)

    def test_template_is_skipped(self):
        self.add_class("_template", "MWF 10:00-10:50")
        got, _ = self.entries()
        self.assertEqual(got, REFRESH)

    def test_two_classes_share_a_slot_without_duplicating_it(self):
        self.add_class("cs-2123", "MWF 10:00-10:50")
        self.add_class("math-2014", "MW 10:00-10:50")
        got, _ = self.entries()
        self.assertEqual(got - REFRESH, {(1, 11, 20), (3, 11, 20), (5, 11, 20)})


if __name__ == "__main__":
    unittest.main()
