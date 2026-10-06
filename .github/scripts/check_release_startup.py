"""Detect initial release startup failures without handling ordinary job failures."""

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode


def api(path, params=None):
    if params:
        path += "?" + urlencode(params)
    result = subprocess.run(
        ["gh", "api", path], check=True, capture_output=True, text=True, timeout=30
    )
    return json.loads(result.stdout)


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_startup(repository, sha, release, workflow, get=api, pause=time.sleep,
                  clock=time.monotonic, timeout=120):
    """Return a confirmed zero-job startup failure, or None for ordinary outcomes.

    Missing or ambiguous runs and API errors fail the monitor, not the release.
    They must never be converted into a startup-failure Slack message.
    """
    deadline = clock() + timeout
    prefix = "repos/{}/actions".format(repository)
    while True:
        result = get(prefix + "/workflows/{}/runs".format(workflow), {
            "event": "release",
            "head_sha": sha,
            "created": ">=" + release["published_at"],
            "per_page": 100,
        })
        if result["total_count"] > 100:
            raise RuntimeError("Too many release runs to identify the target safely")
        matches = [run for run in result["workflow_runs"] if (
            run["event"] == "release"
            and run["head_sha"] == sha
            and run["head_branch"] == release["tag_name"]
            and timestamp(run["created_at"]) >= timestamp(release["published_at"])
        )]
        if len(matches) > 1:
            raise RuntimeError("Multiple publishing runs match this release")
        if matches:
            run_id = matches[0]["id"]
            run = get(prefix + "/runs/{}".format(run_id))
            if run["run_attempt"] != 1:
                # A release publication has one monitor. Publishing reruns are
                # outside its scope; do not report a failure already retried.
                return None
            jobs = get(prefix + "/runs/{}/attempts/1/jobs".format(run_id))
            if jobs["total_count"] > 0:
                return None
            if run["status"] == "completed":
                if run["conclusion"] == "startup_failure":
                    return run
                return None
        if clock() >= deadline:
            raise RuntimeError("Publishing startup could not be determined within 120 seconds")
        pause(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", default="publish-pypi.yml")
    args = parser.parse_args()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if os.environ["GITHUB_EVENT_NAME"] != "release" or event["action"] != "published":
        raise RuntimeError("Only published release events are supported")
    if os.environ["GITHUB_RUN_ATTEMPT"] != "1":
        print("Monitor rerun: no additional notification")
        return
    run = check_startup(
        os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"],
        event["release"], args.workflow,
    )
    if run is None:
        print("No startup-only notification; ordinary outcomes use the publishing workflow")
        return
    # Construct URLs from trusted runner context and the numeric run ID.
    run_url = "{}/{}/actions/runs/{}".format(
        os.environ["GITHUB_SERVER_URL"], os.environ["GITHUB_REPOSITORY"], int(run["id"])
    )
    payload = {
        "text": "Python SDK release could not start. GitHub rejected the publishing "
                "workflow before any job started. Inspect the workflow error: " + run_url
    }
    payload_path = Path(os.environ["RUNNER_TEMP"]) / "release-startup-slack.json"
    payload_path.write_text(json.dumps(payload))
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("notify=true\npayload_path={}\n".format(payload_path))
    print("Confirmed startup failure: " + run_url)


if __name__ == "__main__":
    main()
