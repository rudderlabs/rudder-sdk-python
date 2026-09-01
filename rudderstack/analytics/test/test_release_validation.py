import os
import runpy
import subprocess
import textwrap
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PUBLISH_WORKFLOW = REPOSITORY_ROOT / '.github' / 'workflows' / 'publish-pypi.yml'
VERSION_FILE = REPOSITORY_ROOT / 'rudderstack' / 'analytics' / 'version.py'
VERSION = runpy.run_path(str(VERSION_FILE))['VERSION']


def release_validation_script():
    workflow = PUBLISH_WORKFLOW.read_text(encoding='utf-8')
    validation_step = workflow.split(
        '      - name: Validate release tag and package version\n', 1
    )[1].split('\n      - name:', 1)[0]
    script = validation_step.split('        run: |\n', 1)[1]
    return textwrap.dedent(script)


def run_validation(release_tag, check_syntax=False):
    command = ['bash', '-n'] if check_syntax else ['bash']
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        env={**os.environ, 'RELEASE_TAG': release_tag},
        input=release_validation_script(),
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
