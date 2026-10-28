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

The workflow does not support manual publishing. PyPI rejects an upload when that version already exists (`skip-existing: false`); **never rerun the publication workflow to retry acceptance**. Instead, on `master`, run **Retry published Python package validation** with the exact release `package-version` (including `-rc.N` for a prerelease), existing `release-tag`, and full commit SHA of that tag (`git rev-parse refs/tags/<tag>^{commit}`). The retry requires a SHA-valued GitHub release target matching that commit (branch-valued `target_commitish` cannot independently prove the original commit), checks the published release, tag, checked-out package metadata and public PyPI wheel/sdist, then calls the same full published-package acceptance workflow without an upload path or publishing OIDC permission. A successful retry does not retroactively change the earlier failed publication run or its notification.

The new shared-action caller is **draft-only** until SDK-5961 and SDK-5962 are on the central main branch, the reviewed immutable action SHA and exact input/output contract are verified, and the organization Actions allowlist accepts that SHA. Do not merge or attempt release/validation while the `RESOLVE` marker remains in the acceptance workflow. Hosted live acceptance is deferred until the next normal release; this change is implementation-tested only.

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
