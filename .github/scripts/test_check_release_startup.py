import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import check_release_startup as monitor


RELEASE = {"tag_name": "v2.1.10", "published_at": "2026-09-15T12:00:00Z"}
RUN = {
    "id": 42, "event": "release", "head_sha": "abc", "head_branch": "v2.1.10",
    "created_at": "2026-09-15T12:00:00Z", "run_attempt": 1,
    "status": "completed", "conclusion": "startup_failure",
}


class StartupTests(unittest.TestCase):
    def check(self, runs=None, jobs=0, current=None):
        runs = [copy.deepcopy(RUN)] if runs is None else runs
        current = copy.deepcopy(RUN) if current is None else current

        def get(path, params=None):
            if path.endswith("/runs"):
                self.assertEqual(params["event"], "release")
                self.assertEqual(params["head_sha"], "abc")
                return {"total_count": len(runs), "workflow_runs": runs}
            if path.endswith("/jobs"):
                self.assertTrue(path.endswith("/attempts/1/jobs"))
                return {"total_count": jobs}
            return current

        return monitor.check_startup("org/repo", "abc", RELEASE, "publish-pypi.yml",
                                     get=get, timeout=0)

    def test_zero_job_startup_failure(self):
        self.assertEqual(self.check()["id"], 42)

    def test_ordinary_outcomes_do_not_notify(self):
        for conclusion in ("success", "failure", "cancelled", "timed_out", "startup_failure"):
            with self.subTest(conclusion=conclusion):
                self.assertIsNone(self.check(jobs=2, current=dict(RUN, conclusion=conclusion)))

    def test_zero_jobs_alone_is_not_failure(self):
        for conclusion in ("success", "failure", "cancelled", "skipped"):
            with self.subTest(conclusion=conclusion):
                self.assertIsNone(self.check(current=dict(RUN, conclusion=conclusion)))

    def test_publishing_rerun_does_not_notify(self):
        self.assertIsNone(self.check(current=dict(RUN, run_attempt=2)))

    def test_wrong_release_runs_are_not_selected(self):
        for fields in ({"event": "push"}, {"head_sha": "other"},
                       {"head_branch": "v2.1.9"}, {"created_at": "2026-09-14T12:00:00Z"}):
            with self.subTest(fields=fields), self.assertRaises(RuntimeError):
                self.check(runs=[dict(RUN, **fields)])

    def test_ambiguous_runs_fail_without_notification(self):
        with self.assertRaisesRegex(RuntimeError, "Multiple"):
            self.check(runs=[RUN, dict(RUN, id=43)])

    def test_missing_run_times_out(self):
        with self.assertRaisesRegex(RuntimeError, "could not be determined"):
            self.check(runs=[])

    def test_pending_zero_job_run_times_out(self):
        with self.assertRaises(RuntimeError):
            self.check(current=dict(RUN, status="queued", conclusion=None))

    def test_waits_for_run_visibility(self):
        replies = iter([
            {"total_count": 0, "workflow_runs": []},
            {"total_count": 1, "workflow_runs": [RUN]}, RUN, {"total_count": 0},
        ])
        waits = []
        result = monitor.check_startup(
            "org/repo", "abc", RELEASE, "publish-pypi.yml",
            get=lambda *args: next(replies), pause=waits.append,
        )
        self.assertEqual(result["id"], 42)
        self.assertEqual(waits, [5])

    def test_api_failure_is_not_a_release_failure(self):
        def unavailable(*args):
            raise RuntimeError("API unavailable")
        with self.assertRaisesRegex(RuntimeError, "API unavailable"):
            monitor.check_startup("org/repo", "abc", RELEASE, "publish-pypi.yml", get=unavailable)

    def test_truncated_results_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Too many"):
            monitor.check_startup(
                "org/repo", "abc", RELEASE, "publish-pypi.yml",
                get=lambda *args: {"total_count": 101, "workflow_runs": [RUN]},
            )

    def test_main_writes_payload_only_for_confirmed_failure(self):
        for run in (RUN, None):
            with self.subTest(run=run), tempfile.TemporaryDirectory() as directory:
                event_path = Path(directory) / "event.json"
                output_path = Path(directory) / "output"
                event_path.write_text(json.dumps({"action": "published", "release": RELEASE}))
                env = {
                    "GITHUB_EVENT_PATH": str(event_path), "GITHUB_OUTPUT": str(output_path),
                    "GITHUB_EVENT_NAME": "release", "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_REPOSITORY": "org/repo", "GITHUB_SHA": "abc",
                    "GITHUB_SERVER_URL": "https://github.com", "RUNNER_TEMP": directory,
                }
                with patch.dict(os.environ, env), patch("sys.argv", ["check_release_startup.py"]), \
                        patch.object(monitor, "check_startup", return_value=run):
                    monitor.main()
                self.assertEqual(output_path.exists(), run is not None)
                if run:
                    self.assertIn("notify=true", output_path.read_text())
                    payload = json.loads((Path(directory) / "release-startup-slack.json").read_text())
                    self.assertIn("https://github.com/org/repo/actions/runs/42", payload["text"])

    def test_monitor_rerun_skips_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            event_path.write_text(json.dumps({"action": "published", "release": RELEASE}))
            env = {"GITHUB_EVENT_PATH": str(event_path), "GITHUB_EVENT_NAME": "release",
                   "GITHUB_RUN_ATTEMPT": "2"}
            with patch.dict(os.environ, env), patch("sys.argv", ["check_release_startup.py"]), \
                    patch.object(monitor, "check_startup") as check:
                monitor.main()
                check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
