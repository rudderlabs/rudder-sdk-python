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

The workflow sends the Slack release notification only after PyPI accepts the package.

## Publish an existing GitHub release

Use this procedure when a GitHub release exists but its package is missing from PyPI.

1. Open the repository's **Actions** page.
2. Select **Publish to PyPI**.
3. Select **Run workflow** from `master`.
4. Enter the existing release tag, for example `v2.1.6`.
5. Approve the `pypi` environment deployment if GitHub requests approval.
6. Wait for the build and publish jobs to finish.
7. Verify the package installation.

A manual run does not send a second Slack notification.

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
