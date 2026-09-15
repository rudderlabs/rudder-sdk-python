# Release startup-failure validation

Date: 2026-09-15

Tracking issue: [SDK-5414](https://linear.app/rudderstack/issue/SDK-5414/investigate-python-release-startup-failure-notifications)

## Decision

Use an independent `release: published` workflow to detect a zero-job publishing
startup failure through the Actions API. Do not use `workflow_run: completed`
for this failure path. In the controlled proof, ordinary outcomes triggered the
lifecycle observers, but policy-rejected runs did not.

The [original publishing failure](https://github.com/rudderlabs/rudder-sdk-python/actions/runs/33517986519)
has `status: completed`, `conclusion: startup_failure`, `run_attempt: 1`, and zero
jobs. The check suite also has zero check runs. The existing in-workflow Slack
job cannot execute in that state.

## Controlled proof

A private [synthetic repository](https://github.com/dciccale/sdk-5414-startup-failure-proof)
contains no SDK source, publishing credentials, or Slack credentials. Its
selected-actions policy initially allowed checkout and rejected setup-python.
This reproduces the action-allowlist failure class; it does not reproduce every
organization rule. No production repository policy was changed.

The valid lifecycle observers were present on the default branch before the
release events. They watched the exact synthetic workflow names. One watched
`completed`; the other watched `requested`, `in_progress`, and `completed`.

| Case | Evidence | Result |
| --- | --- | --- |
| Ordinary success | [source run](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34962833080), [completion observer](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34962855875) | Completion event received; two jobs exist. |
| Ordinary failure | [source run](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34962836040), [completion observer](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34962860451) | Completion event received; two jobs exist. |
| Policy rejection on release | [source run](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34963028077), [release API observer](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34963026994) | `startup_failure`, zero jobs; API observer detected it. No matching lifecycle observer run was observed. |
| Actual detector, policy rejection | [source run](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34963381923), [detector attempt 1](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34963380765/attempts/1) | Detector generated one payload; notification stand-in ran once. |
| Actual detector, ordinary success | [source run](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34963425567), [detector](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34963425742) | New notification skipped; existing notification stand-in ran. |
| Actual detector, ordinary failure | [source run](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34963426825), [detector](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34963426804) | New notification skipped; existing notification stand-in handles the ordinary failure. |
| Monitor rerun | [detector attempt 2](https://github.com/dciccale/sdk-5414-startup-failure-proof/actions/runs/34963380765/attempts/2) | Detection job skipped; no second payload or notification. |

The production detector script was copied unchanged into the proof repository.
The proof passed `--workflow release.yml` to target the synthetic publisher.
Its notification step printed the JSON payload instead of sending it to Slack.
The production workflow additionally uses the repository's existing harden-runner
and Slack action pins. Their policy approval was checked against the repository's
current selected-actions settings. Actual Slack delivery was not exercised.

## Detection rule

1. Query the target publishing workflow for release runs at the event's commit.
2. Match the release tag and creation time at or after `published_at`.
3. Require one unambiguous matching run.
4. Read the current run and the first attempt's jobs.
5. Alert only when attempt 1 is completed with `startup_failure` and zero jobs.

The monitor polls for up to two minutes while the run is absent or has not yet
created jobs. Once any job exists, ordinary publishing notification owns the
outcome. Ambiguous matches, API errors, incomplete results, and a discovery
timeout fail the monitor without claiming a release startup failure.

Run matching includes the release time so an older release at the same tag and
commit cannot be mistaken for the new release. Publishing reruns are ignored.
Monitor reruns are skipped at both workflow and script levels. This prevents
overlap with ordinary notifications and repetition from manual monitor reruns;
it is not an exactly-once delivery guarantee from Slack.

## Permissions and limits

- `actions: read` permits run and job queries; `contents: read` permits checkout.
- The existing repository Slack token and channel are used only by the sending step.
- The monitor has no `id-token: write`, publishing environment, or package upload step.
- All action references reuse existing full SHA pins. Policy must continue to allow them.
- The release tag must contain the monitor and detector script. Older tags are not covered.
- A missing release event, disabled Actions, or a failure of the monitor itself is not covered.
- A missing or delayed publishing run beyond the discovery window is reported only in Actions.
- Later publishing attempts and automatic resending after Slack errors are not covered.
- The proof establishes action-policy rejection. Other zero-job failure classes require separate evidence.

If the monitor fails, inspect its logs. A rerun cannot resend the alert. Check the
publishing run directly and use the existing release recovery procedure. A broader
monitor would need a separate retry and durable deduplication design.

## Reproduce the checks

1. Run `python3 -m unittest discover -s .github/scripts -p 'test_*.py'`.
2. Run actionlint against all repository workflows.
3. In an isolated repository, install the synthetic publisher and observers on the default branch.
4. Configure selected actions to allow the monitor and reject one publisher action.
5. Publish a synthetic release and inspect the failed run and monitor output.
6. Allow the publisher action and repeat with ordinary success and failure.
7. Rerun the monitor and confirm its detection job is skipped.

The focused tests cover delayed visibility, matching, ambiguous and missing runs,
API failure, ordinary outcomes, zero-job non-startup outcomes, and rerun suppression.

References: [workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[workflow-run API](https://docs.github.com/en/rest/actions/workflow-runs).
