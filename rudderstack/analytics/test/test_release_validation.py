import os
import runpy
import subprocess
from pathlib import Path

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PUBLISH_WORKFLOW = REPOSITORY_ROOT / '.github' / 'workflows' / 'publish-pypi.yml'
VERSION_FILE = REPOSITORY_ROOT / 'rudderstack' / 'analytics' / 'version.py'
VERSION = runpy.run_path(str(VERSION_FILE))['VERSION']
ACCEPT_WORKFLOW = REPOSITORY_ROOT / '.github' / 'workflows' / 'accept-published-package.yml'


class WorkflowLoader(yaml.SafeLoader):
    pass


# PyYAML treats `on` as a YAML 1.1 boolean, unlike GitHub Actions.
WorkflowLoader.yaml_implicit_resolvers = {
    key: [item for item in resolvers if key not in 'oO' or
          item[0] != 'tag:yaml.org,2002:bool']
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def workflow(path):
    return yaml.load(path.read_text(encoding='utf-8'), Loader=WorkflowLoader)


def step(path, job, name):
    return next(item for item in workflow(path)['jobs'][job]['steps']
                if item['name'] == name)


def validation_step():
    return step(PUBLISH_WORKFLOW, 'build', 'Validate release tag and package version')


def run_validation(release_tag, check_syntax=False, output=None):
    command = ['bash', '-n'] if check_syntax else ['bash']
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        env={**os.environ, 'RELEASE_TAG': release_tag,
             **({'GITHUB_OUTPUT': str(output)} if output else {})},
        input=validation_step()['run'],
        text=True,
    )


def test_release_validation_script_has_valid_shell_syntax():
    result = run_validation('v{}'.format(VERSION), check_syntax=True)

    assert result.returncode == 0


def test_current_package_version_matches_release_tag():
    result = run_validation('v{}'.format(VERSION))

    assert result.returncode == 0


@pytest.mark.parametrize('release_tag', ['2.1.7', 'v2.1', 'release-v2.1.7'])
def test_invalid_release_tag_is_rejected(release_tag):
    result = run_validation(release_tag)

    assert result.returncode == 1
    assert 'Invalid release tag' in result.stderr


def test_release_tag_must_match_package_version():
    result = run_validation('v999.0.0')

    assert result.returncode == 1
    assert 'does not match package version' in result.stderr


def test_build_exports_validated_version(tmp_path):
    output = tmp_path / 'outputs'
    result = run_validation('v{}'.format(VERSION), output=output)
    assert result.returncode == 0, result.stderr
    assert output.read_text() == 'package-version={}\n'.format(VERSION)


@pytest.mark.parametrize('event,ref_type,tag,version,valid', [
    ('release', 'tag', 'v1.2.3', '1.2.3', True),
    ('workflow_dispatch', 'tag', 'v1.2.3', 'v1.2.3', True),
    ('workflow_dispatch', 'branch', 'master', '1.2.3', False),
    ('pull_request', 'tag', 'v1.2.3', '1.2.3', False),
    ('push', 'tag', 'v1.2.3', '1.2.3', False),
    ('release', 'tag', 'v1.2.3', '1.2.4', False),
    ('release', 'tag', 'v1.2.3', 'latest', False),
    ('release', 'tag', 'v01.2.3', '01.2.3', False),
    ('release', 'tag', 'v1.2.3-rc.1', '1.2.3-rc.1', False),
    ('workflow_dispatch', 'tag', 'v1.2.3;echo bad', '1.2.3;echo bad', False),
])
def test_acceptance_guard(event, ref_type, tag, version, valid, tmp_path):
    guard = step(ACCEPT_WORKFLOW, 'validate', 'Require an exact release tag')['run']
    result = subprocess.run(
        ['bash'], input=guard, text=True, capture_output=True, check=False,
        cwd=tmp_path, env={**os.environ, 'GITHUB_EVENT_NAME': event,
                           'GITHUB_REF_TYPE': ref_type, 'RELEASE_TAG': tag,
                           'PACKAGE_VERSION': version},
    )
    assert (result.returncode == 0) == valid, result.stderr


def test_publication_waits_for_acceptance_and_preserves_upload_controls():
    jobs = workflow(PUBLISH_WORKFLOW)['jobs']
    build, publish, accept, notify = (jobs[key] for key in
                                    ('build', 'publish', 'accept-published', 'notify-slack'))
    assert build['outputs']['package-version'] == '${{ steps.validate.outputs.package-version }}'
    checkout = next(item for item in build['steps'] if 'checkout@' in item.get('uses', ''))
    # Use the immutable event-time SHA. Never resolve the tag again during build.
    assert 'ref' not in checkout.get('with', {})
    assert publish['needs'] == 'build'
    assert publish['environment']['name'] == 'pypi'
    assert publish['permissions'] == {'id-token': 'write'}
    upload = next(item for item in publish['steps'] if 'pypi-publish@' in item.get('uses', ''))
    assert upload['with']['skip-existing'] is False
    assert accept['needs'] == ['build', 'publish']
    assert accept['with'] == {'package-version': '${{ needs.build.outputs.package-version }}'}
    assert accept['secrets'] == {'RELEASE_PRIVATE_KEY': '${{ secrets.RELEASE_PRIVATE_KEY }}'}
    assert set(notify['needs']) == {'build', 'publish', 'accept-published'}
    assert any('twine check' in item.get('run', '') for item in build['steps'])


def test_notification_distinguishes_publication_from_acceptance():
    notify = workflow(PUBLISH_WORKFLOW)['jobs']['notify-slack']
    steps = {item['name']: item for item in notify['steps']}
    success = steps['Send success message to Slack channel']['if']
    failed_acceptance = steps['Report published package with failed acceptance']['if']
    assert all("needs.{}.result == 'success'".format(job) in success
               for job in ('build', 'publish', 'accept-published'))
    assert "needs.publish.result == 'success'" in failed_acceptance
    assert "needs.accept-published.result != 'success'" in failed_acceptance
    assert 'always()' in notify['if']
    assert workflow(PUBLISH_WORKFLOW)['concurrency']['cancel-in-progress'] is False


def test_retry_has_no_upload_path_and_uses_the_shared_action_contract():
    accept = workflow(ACCEPT_WORKFLOW)
    assert set(accept['on']) == {'workflow_call', 'workflow_dispatch'}
    assert not accept['on']['workflow_dispatch']  # The selected tag supplies version and commit.
    assert accept['permissions'] == {'contents': 'read'}
    assert list(accept['jobs']) == ['validate']
    job = accept['jobs']['validate']
    assert 'if' not in job  # Invalid inputs fail; acceptance must not silently skip.
    assert 'concurrency' not in accept  # Central workflow owns live locking and cleanup.
    steps = job['steps']
    uses = [item.get('uses', '') for item in steps]
    assert not any('checkout@' in action or 'pypi-publish@' in action for action in uses)
    token = next(item for item in steps if 'create-github-app-token@' in item.get('uses', ''))
    assert token['with']['repositories'] == 'rudder-sdk-e2e-tests'
    assert token['with']['permission-actions'] == 'write'
    assert not any(key.startswith('permission-') and key != 'permission-actions'
                   for key in token['with'])
    action = steps[-1]
    repository, sha = action['uses'].split('@')
    assert repository == 'rudderlabs/github-action-sdk-e2e'
    assert len(sha) == 40 and set(sha) <= set('0123456789abcdef') and set(sha) != {'0'}
    assert set(action['with']) == {'token', 'package-version', 'suite'}
    assert action['with']['suite'] == 'full'
    assert action['with']['package-version'] == '${{ inputs.package-version || github.ref_name }}'
    # Provenance and registry installation belong to the central workflow.
    text = ACCEPT_WORKFLOW.read_text()
    assert 'target_commitish' not in text
    assert 'pypi.org' not in text
