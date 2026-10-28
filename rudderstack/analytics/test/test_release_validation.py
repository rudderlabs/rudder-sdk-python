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
RETRY_WORKFLOW = REPOSITORY_ROOT / '.github' / 'workflows' / 'retry-published-validation.yml'


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


def test_build_exports_validated_version_and_checked_out_commit(tmp_path):
    output = tmp_path / 'outputs'
    result = run_validation('v{}'.format(VERSION), output=output)
    assert result.returncode == 0, result.stderr
    values = output.read_text()
    assert 'package-version={}\n'.format(VERSION) in values
    assert 'release-commit={}\n'.format(subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=REPOSITORY_ROOT, text=True).strip()) in values


def acceptance_step(name):
    return step(ACCEPT_WORKFLOW, 'accept', name)


def run_acceptance_guard(tmp_path, version, tag, commit, event_name='workflow_dispatch', event_tag=''):
    script = acceptance_step('Validate caller inputs')['run']
    return subprocess.run(
        ['bash'], input=script, text=True, check=False, capture_output=True,
        cwd=tmp_path, env={**os.environ, 'RELEASE_TAG': tag, 'PACKAGE_VERSION': version,
                           'RELEASE_COMMIT': commit, 'EVENT_NAME': event_name,
                           'EVENT_RELEASE_TAG': event_tag},
    )


@pytest.mark.parametrize('version,tag,commit,valid', [
    ('1.2.3', 'v1.2.3', 'a' * 40, True),
    ('1.2.3-rc.1', 'v1.2.3-rc.1', 'a' * 40, True),
    ('1.2.3', 'v1.2.4', 'a' * 40, False),
    ('1.2.3', 'v1.2.3', 'short', False),
    ('latest', 'vlatest', 'a' * 40, False),
    ('1.2.3', 'v1.2.3;echo bad', 'a' * 40, False),
])
def test_acceptance_input_guard(tmp_path, version, tag, commit, valid):
    result = run_acceptance_guard(tmp_path, version, tag, commit)
    assert (result.returncode == 0) == valid


def test_release_event_tag_must_match_input(tmp_path):
    assert run_acceptance_guard(tmp_path, '1.2.3', 'v1.2.3', 'a' * 40,
                                'release', 'v1.2.4').returncode == 1
    assert run_acceptance_guard(tmp_path, '1.2.3', 'v1.2.3', 'a' * 40,
                                'release', 'v1.2.3').returncode == 0


def test_release_jobs_pass_exact_outputs_only_after_upload():
    jobs = workflow(PUBLISH_WORKFLOW)['jobs']
    build, publish, accept, notify = (jobs[key] for key in
                                      ('build', 'publish', 'accept-published', 'notify-slack'))
    assert build['outputs'] == {
        'package-version': '${{ steps.validate.outputs.package-version }}',
        'release-commit': '${{ steps.validate.outputs.release-commit }}',
    }
    assert validation_step()['id'] == 'validate'
    assert 'git rev-parse HEAD' in validation_step()['run']
    assert publish['needs'] == 'build'
    assert publish['environment']['name'] == 'pypi'
    assert publish['permissions'] == {'id-token': 'write'}
    assert next(step for step in publish['steps'] if 'pypi-publish@' in step.get('uses', ''))[
        'with']['skip-existing'] is False
    assert accept['needs'] == ['build', 'publish']
    assert accept['with'] == {
        'package-version': '${{ needs.build.outputs.package-version }}',
        'release-tag': '${{ github.event.release.tag_name }}',
        'release-commit': '${{ needs.build.outputs.release-commit }}',
    }
    assert accept['secrets'] == {'release-private-key': '${{ secrets.RELEASE_PRIVATE_KEY }}'}
    assert notify['needs'] == ['build', 'publish', 'accept-published']
    assert jobs['build']['steps'][-1]['with']['retention-days'] == 1
    assert any('twine check' in step.get('run', '') for step in build['steps'])


def test_notification_requires_completed_acceptance():
    notify = workflow(PUBLISH_WORKFLOW)['jobs']['notify-slack']
    steps = {step['name']: step for step in notify['steps']}
    success = steps['Send success message to Slack channel']['if']
    failed_acceptance = steps['Report published package with failed acceptance']['if']
    assert all("needs.{}.result == 'success'".format(job) in success
               for job in ('build', 'publish', 'accept-published'))
    assert "needs.publish.result == 'success'" in failed_acceptance
    assert "needs.accept-published.result != 'success'" in failed_acceptance
    assert 'always()' in notify['if']
    assert 'cancel-in-progress: false' in PUBLISH_WORKFLOW.read_text()


def test_retry_is_manual_and_cannot_publish():
    retry = workflow(RETRY_WORKFLOW)
    assert retry['on']['workflow_dispatch']['inputs'].keys() == {
        'package-version', 'release-tag', 'release-commit'
    }
    assert retry['permissions'] == {}
    assert retry['concurrency']['cancel-in-progress'] is False
    assert list(retry['jobs']) == ['accept-published']
    caller = retry['jobs']['accept-published']
    assert caller['uses'] == './.github/workflows/accept-published-package.yml'
    assert caller['permissions'] == {'contents': 'read'}
    assert "github.ref == 'refs/heads/master'" in caller['if']
    assert caller['with'] == {
        'package-version': '${{ inputs.package-version }}',
        'release-tag': '${{ inputs.release-tag }}',
        'release-commit': '${{ inputs.release-commit }}',
    }
    assert 'secrets: inherit' not in RETRY_WORKFLOW.read_text()
    assert 'pypi-publish@' not in RETRY_WORKFLOW.read_text()


def test_acceptance_checks_provenance_and_registry_before_token():
    accept = workflow(ACCEPT_WORKFLOW)['jobs']['accept']
    assert "github.event.action == 'published'" in accept['if']
    assert "github.ref == 'refs/heads/master'" in accept['if']
    assert accept['permissions'] == {'contents': 'read'}
    steps = accept['steps']
    names = [step['name'] for step in steps]
    assert names.index('Check tag commit and package metadata') < names.index(
        'Verify exact public PyPI distributions') < names.index(
            'Generate repository-scoped GitHub App token') < names.index(
                'Run exact published-package full E2E')
    provenance = acceptance_step('Check tag commit and package metadata')['run']
    assert 'git rev-parse HEAD' in provenance
    assert 'releases/tags/$RELEASE_TAG' in provenance
    assert 'ast.parse' in provenance
    assert 'runpy' not in provenance
    assert 'git merge-base --is-ancestor' in provenance
    assert '.target_commitish' in provenance
    registry = acceptance_step('Verify exact public PyPI distributions')['run']
    assert "requested.replace('-rc.', 'rc')" in registry
    assert 'range(20)' in registry
    assert "{'bdist_wheel', 'sdist'}" in registry
    token = acceptance_step('Generate repository-scoped GitHub App token')['with']
    assert token['repositories'] == 'rudder-sdk-e2e-tests'
    assert token['permission-actions'] == 'write'
    assert not any(key.startswith('permission-') and key != 'permission-actions' for key in token)
    action = acceptance_step('Run exact published-package full E2E')
    assert action['with']['package-version'] == '${{ steps.verify-pypi.outputs.canonical-version }}'
    assert action['with']['release-commit'] == '${{ inputs.release-commit }}'
    assert action['with']['mode'] == 'published'
    assert action['with']['suite'] == 'full'
    assert action['uses'].startswith('rudderlabs/rudder-sdk-e2e-tests/.github/actions/server-sdk-e2e@')
    assert len(action['uses'].rsplit('@', 1)[1]) == 40
    assert all(character in '0123456789abcdef' for character in action['uses'].rsplit('@', 1)[1])
