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

The workflow sends a release-complete notification only after the wheel and sdist pass validation, PyPI accepts them, and the shared full E2E suite accepts **that exact version from public PyPI** (including delivery and cleanup). A published version whose acceptance fails or is skipped remains published: the workflow reports this separately, with the run link, and does not unpublish it. Build or upload failures also produce a failure notification. The PR native test/quality suite is not a source-candidate full E2E suite for Python.

The workflow does not support manual publishing. PyPI rejects duplicate uploads (`skip-existing: false`). Retry acceptance with **Published Python SDK E2E**, selecting the existing release tag as the workflow ref:

```sh
gh workflow run accept-published-package.yml --repo rudderlabs/rudder-sdk-python --ref vX.Y.Z
```

The retry uses the tag's event-time commit and exact version. It cannot upload packages. The central workflow checks the tag's commit, its ancestry on `master`, public PyPI metadata, and the installed wheel's version and SHA-256. A release whose `target_commitish` names a branch is valid; that field is not used as commit proof. The shared action waits for delivery validation and cleanup before returning.

Published E2E currently accepts stable `X.Y.Z` versions only. Tags must contain this workflow, so older tags need an exact-version dispatch through the central workflow instead. A successful retry does not change the original failed run or its notification. A published package remains published if acceptance fails.

This caller depends on [central PR #32](https://github.com/rudderlabs/rudder-sdk-e2e-tests/pull/32) and [shared-action PR #5](https://github.com/rudderlabs/github-action-sdk-e2e/pull/5). The action is pinned to an existing commit from PR #5. Keep this PR draft until both dependencies are reviewed and merged, then verify or refresh the pin. Hosted live acceptance remains pending the next normal release.

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
