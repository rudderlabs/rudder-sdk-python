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

The workflow accepts stable `X.Y.Z` releases only, and checks that policy before upload. It sends a release-complete notification only after the wheel and sdist pass validation, PyPI accepts them, and the shared full E2E suite accepts **that exact version from public PyPI** (including delivery and cleanup). A published version whose acceptance fails or is skipped remains published: the workflow reports “published; validation failed or incomplete” and does not unpublish it. Build or upload failures also produce a failure notification. Only the first release-run attempt sends a notification. Reruns remain silent. Each notification has a short channel message and a non-broadcast thread reply with links, available central-run diagnostics, and check results. Notification failures remain visible in the workflow summary. The PR native test/quality suite is not a source-candidate full E2E suite for Python.

The workflow does not support manual publishing. PyPI rejects duplicate uploads (`skip-existing: false`). Retry acceptance with **Published Python SDK E2E**, selecting the existing release tag as the workflow ref:

```sh
gh workflow run accept-published-package.yml --repo rudderlabs/rudder-sdk-python --ref vX.Y.Z
```

The retry uses the tag's event-time commit and exact version. It cannot upload packages. The central workflow checks the tag's commit, its ancestry on `master`, public PyPI metadata, and the installed wheel's version and SHA-256. A release whose `target_commitish` names a branch is valid; that field is not used as commit proof. The shared action waits for delivery validation and cleanup before returning.

Published E2E currently accepts stable `X.Y.Z` versions only. Tags must contain this workflow, so older tags need an exact-version dispatch through the central workflow instead. A successful retry does not change the original failed run or its notification. A published package remains published if acceptance fails.

The caller pins shared-action #14 at `2d1262f86e519195dc723a8d244a8ecc8bcedb21` for full live delivery and verified per-run cleanup. Coordinate activation with central #46/#47 under [SDK-6016](https://linear.app/rudderstack/issue/SDK-6016). Hosted acceptance remains pending the next normal release under [SDK-5797](https://linear.app/rudderstack/issue/SDK-5797).

## Retry after a workflow fix

A tag retry uses workflow code and pins stored at that tag. The retry workflow
must exist on the default branch and selected tag. If a later workflow fix is
needed, use the current central workflow. Copy the full commit SHA from the
original release run. Replace the version, commit placeholder, and request ID:

```sh
gh workflow run server-sdk-validation.yml --repo rudderlabs/rudder-sdk-e2e-tests --ref main \
  -f selection=auto -f source_repository=rudderlabs/rudder-sdk-python \
  -f source_sha=RELEASE_EVENT_COMMIT_SHA -f package_version=X.Y.Z \
  -f suite=full -f request_id=python-published-X_Y_Z-retry-UNIQUE_ID
```

This validates the published version without uploading or announcing. Record the
new evidence in the release ticket and existing release thread. Do not move the
tag. A failed first-attempt notification needs a separate thread repair; rerunning
all publishing jobs does not send another announcement.

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
