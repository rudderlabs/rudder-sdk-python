"""Keep package metadata readable before SDK dependencies are installed."""
import runpy
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_setup_version_does_not_import_sdk():
    script = '''
import importlib.abc
import runpy
import sys
import types

# Capture metadata without requiring setuptools in the test environment.
setuptools = types.ModuleType("setuptools")
setuptools.setup = lambda **metadata: print(metadata["version"])
sys.modules["setuptools"] = setuptools

class BlockSDKImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "rudderstack" or fullname.startswith("rudderstack."):
            raise AssertionError("Package metadata must not import the SDK")

sys.meta_path.insert(0, BlockSDKImports())
sys.argv = ["setup.py", "--version"]
runpy.run_path("setup.py", run_name="__main__")
'''
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=REPOSITORY_ROOT,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        runpy.run_path(
            str(REPOSITORY_ROOT / 'rudderstack/analytics/version.py')
        )['VERSION']
    )
