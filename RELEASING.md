# Releasing the Python SDK

The repository uses release-please for versioning and GitHub releases. A separate workflow publishes each release to PyPI.

## Normal release

1. Merge user-facing changes into `master` with Conventional Commit titles.
2. Review and merge the release-please pull request.
3. Wait for the `Publish to PyPI` workflow to finish.
4. Verify the new version on [PyPI](https://pypi.org/project/rudder-sdk-python/).
5. Install the published version in a clean environment:

   ```sh
   python -m pip install --no-cache-dir rudder-sdk-python==<version>
   python -c "from rudderstack.analytics.version import VERSION; print(VERSION)"
   ```

The workflow sends the successful release notification only after PyPI accepts the package. If the build or publication fails, the workflow sends a failure notification with a link to the GitHub Actions run. PyPI rejects an upload when that version already exists, and the workflow reports that rejection as a failure.

The workflow does not support manual publishing.

## Startup failures

`Notify release startup failure` independently handles the initial publishing
attempt when GitHub rejects the workflow before creating any jobs. Both workflows
start from `release: published`. The monitor queries the Actions API for up to
two minutes and sends a Slack alert only for `startup_failure` with zero jobs.
Ordinary job outcomes continue to use the publishing workflow's notification.

The monitor deliberately skips reruns to avoid repeating the initial alert. It
also skips a publishing run that has already been retried. Inspect the failed
workflow and correct the reported configuration or action-policy error before
retrying publishing. A monitor failure, missing run, or API error is visible in
Actions but is not reported as a publishing startup failure in Slack.

This covers releases whose tag includes the monitor. It does not cover disabled
Actions, a rejected monitor, missing release events, or startup failures on later
publishing attempts. See [the validation record](docs/release-startup-validation.md)
for the controlled proof and detection limits.

## Authentication

PyPI uses a trusted publisher for this repository. GitHub obtains a short-lived OpenID Connect token for each publishing job. The repository does not store a PyPI password or API token.

The PyPI publisher must use these values:

| Field | Value |
| --- | --- |
| Owner | `rudderlabs` |
| Repository | `rudder-sdk-python` |
| Workflow | `publish-pypi.yml` |
| Environment | `pypi` |

The publishing job must keep the `id-token: write` permission. Build steps must remain in the separate build job.
