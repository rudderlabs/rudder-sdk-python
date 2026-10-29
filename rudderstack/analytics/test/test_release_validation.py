import json
import os
import re
import runpy
import shutil
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


def require_tools(*names):
    for name in names:
        if shutil.which(name) is None:
            pytest.skip('{} is required for this workflow script test'.format(name))


def run_validation(release_tag, check_syntax=False, output=None, cwd=REPOSITORY_ROOT,
                   prerelease='false', draft='false'):
    require_tools('bash')
    command = ['bash', '-n'] if check_syntax else ['bash']
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        cwd=cwd,
        env={**os.environ, 'RELEASE_TAG': release_tag,
             'RELEASE_PRERELEASE': prerelease, 'RELEASE_DRAFT': draft,
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


@pytest.mark.parametrize('release_tag', ['2.1.7', 'v2.1', 'release-v2.1.7',
                                         'v1.2.3.post1', 'v1.2.3-rc.1', 'v01.2.3'])
def test_invalid_release_tag_is_rejected(release_tag):
    result = run_validation(release_tag)

    assert result.returncode == 1
    assert 'Invalid stable release tag' in result.stderr


def test_post_release_version_is_rejected_before_upload(tmp_path):
    version_file = tmp_path / 'rudderstack' / 'analytics' / 'version.py'
    version_file.parent.mkdir(parents=True)
    version_file.write_text("VERSION = '1.2.3.post1'\n", encoding='utf-8')

    result = run_validation('v1.2.3', cwd=tmp_path)

    assert result.returncode == 1
    assert 'does not match package version 1.2.3.post1' in result.stderr


def test_release_tag_must_match_package_version():
    result = run_validation('v999.0.0')

    assert result.returncode == 1
    assert 'does not match package version' in result.stderr


def test_build_exports_validated_version(tmp_path):
    output = tmp_path / 'outputs'
    result = run_validation('v{}'.format(VERSION), output=output)
    assert result.returncode == 0, result.stderr
    assert output.read_text() == 'package-version={}\n'.format(VERSION)


@pytest.mark.parametrize('prerelease,draft', [('true', 'false'), ('false', 'true'), ('', 'false')])
def test_release_metadata_rejects_unsupported_events_before_upload(prerelease, draft):
    result = run_validation('v{}'.format(VERSION), prerelease=prerelease, draft=draft)
    assert result.returncode == 1
    assert 'non-draft, non-prerelease' in result.stderr
    assert validation_step()['env'] == {
        'RELEASE_PRERELEASE': '${{ github.event.release.prerelease }}',
        'RELEASE_DRAFT': '${{ github.event.release.draft }}',
    }



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
    prepare = steps['Prepare release notification']
    root = steps['Post release status to Slack']
    thread = steps['Post release details in thread']
    assert root['id'] == 'root'
    assert root['uses'] == thread['uses']
    assert root['with']['channel-id'] == thread['with']['channel-id']
    assert root['with']['payload'] == '${{ steps.notification.outputs.root_payload }}'
    assert thread['with']['payload'].count('steps.root.outputs.ts') == 1
    assert '"reply_broadcast": false' in thread['with']['payload']
    assert all('"{}": false'.format(field) in thread['with']['payload']
               for field in ('unfurl_links', 'unfurl_media'))
    assert 'needs.build.outputs.package-version' in prepare['env']['RELEASE_VERSION']
    assert 'always()' in notify['if']
    assert "github.run_attempt == '1'" in notify['if']
    assert thread['if'] == "steps.root.outputs.ts != ''"
    assert workflow(PUBLISH_WORKFLOW)['concurrency']['cancel-in-progress'] is False


def test_pr_matrix_keeps_old_python_on_ubuntu_24_04():
    matrix = workflow(REPOSITORY_ROOT / '.github' / 'workflows' / 'build.yml')['jobs']['build']
    assert matrix['runs-on'] == '${{ matrix.runner }}'
    assert matrix['strategy']['matrix']['include'] == [
        {'python-version': version, 'runner': 'ubuntu-24.04' if version in ('3.8', '3.9')
         else 'ubuntu-latest'}
        for version in ('3.8', '3.9', '3.10', '3.11', '3.12')
    ]


@pytest.mark.parametrize('build,publish,accept,status,registry', [
    ('success', 'success', 'success', 'release complete', 'exact public PyPI version verified'),
    ('success', 'failure', 'skipped', 'build or upload failed or incomplete', 'upload not confirmed'),
    ('failure', 'skipped', 'skipped', 'build or upload failed or incomplete', 'upload not confirmed'),
    ('success', 'success', 'failure', 'published; validation failed or incomplete',
     'published on PyPI; validation failed or incomplete'),
    ('success', 'success', 'skipped', 'published; validation failed or incomplete',
     'published on PyPI; validation failed or incomplete'),
])
def test_notification_status_and_thread_details(build, publish, accept, status, registry,
                                                tmp_path):
    require_tools('bash', 'jq')
    script = step(PUBLISH_WORKFLOW, 'notify-slack', 'Prepare release notification')['run']
    output = tmp_path / 'notification-outputs'
    result = subprocess.run(
        ['bash'], input=script, text=True, capture_output=True, check=False,
        env={**os.environ, 'GITHUB_OUTPUT': str(output), 'RELEASE_VERSION': '1.2.3',
             'RELEASE_URL': 'https://example.test/releases/v1.2.3',
             'BUILD_RESULT': build, 'PUBLISH_RESULT': publish, 'ACCEPT_RESULT': accept,
             'GITHUB_SERVER_URL': 'https://example.test', 'GITHUB_REPOSITORY': 'rudderlabs/rudder-sdk-python',
             'GITHUB_RUN_ID': '123', 'CENTRAL_RUN_URL': 'https://example.test/central-run',
             'GITHUB_STEP_SUMMARY': str(tmp_path / 'summary')},
    )
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split('=', 1) for line in output.read_text().splitlines())
    root = json.loads(outputs['root_payload'])
    details = json.loads(outputs['detail_json'])
    assert re.search(r'Python SDK v1\.2\.3 · \d{4}-\d{2}-\d{2} · ' + re.escape(status), root['text'])
    assert '<!subteam^S03SW7DM8P3>' in root['text']
    assert root['unfurl_links'] is False and root['unfurl_media'] is False
    assert registry in details
    assert 'https://example.test/central-run' in details
    assert status in (tmp_path / 'summary').read_text()
    assert 'build {}, upload {}, acceptance {}'.format(build, publish, accept) in details
    assert '<https://example.test/rudderlabs/rudder-sdk-python/actions/runs/123|view workflow>' in details
    assert ('*PyPI:*' in details) == (publish == 'success')
    assert ('*Retry:*' in details) == (publish == 'success' and accept != 'success')


@pytest.mark.parametrize('root,ts,reply,accepted', [
    ('success', '123.456', 'success', True),
    ('failure', '', 'skipped', False),
    ('success', '', 'skipped', False),
    ('success', 'invalid', 'success', False),
    ('success', '123.456', 'failure', False),
])
def test_notification_requires_confirmed_root_and_reply(root, ts, reply, accepted, tmp_path):
    require_tools('bash')
    script = step(PUBLISH_WORKFLOW, 'notify-slack', 'Require confirmed release notification')['run']
    result = subprocess.run(
        ['bash', '-e', '-c', script], text=True, capture_output=True,
        env={**os.environ, 'ROOT_RESULT': root, 'ROOT_TS': ts, 'REPLY_RESULT': reply,
             'GITHUB_STEP_SUMMARY': str(tmp_path / 'summary')},
    )
    assert (result.returncode == 0) == accepted


def test_retry_has_no_upload_path_and_uses_the_shared_action_contract():
    accept = workflow(ACCEPT_WORKFLOW)
    assert set(accept['on']) == {'workflow_call', 'workflow_dispatch'}
    assert not accept['on']['workflow_dispatch']  # The selected tag supplies version and commit.
    assert accept['permissions'] == {'contents': 'read'}
    assert list(accept['jobs']) == ['validate']
    job = accept['jobs']['validate']
    assert 'steps' not in job and 'runs-on' not in job
    path, sha = job['uses'].split('@')
    assert path == 'rudderlabs/github-action-sdk-e2e/.github/workflows/published-sdk-e2e.yml'
    assert re.fullmatch('[0-9a-f]{40}', sha)
    assert sha == 'b6de40cc65abe8ee6c6593aac1787aea746b671f'
    assert job['with'] == {
        'package-version': '${{ inputs.package-version || github.ref_name }}',
        'release-app-client-id': '${{ vars.RELEASE_APP_CLIENT_ID }}',
    }
    assert job['secrets'] == {'RELEASE_PRIVATE_KEY': '${{ secrets.RELEASE_PRIVATE_KEY }}'}
    assert 'SLACK' not in str(accept) and 'id-token: write' not in ACCEPT_WORKFLOW.read_text()
