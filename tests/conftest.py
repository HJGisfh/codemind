"""Offline tests: never load developer credentials or write runtime state in the repo."""
import os
import sys
import tempfile
from pathlib import Path
import dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_original_cwd = Path.cwd()
_test_home = tempfile.TemporaryDirectory(prefix="codemind-tests-")
os.chdir(_test_home.name)
os.environ["ANTHROPIC_API_KEY"] = "test-not-a-real-key"
os.environ["MODEL_ID"] = "test-model"
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:1"
dotenv.load_dotenv = lambda *a, **kw: False


def pytest_sessionfinish(session, exitstatus):
    os.chdir(_original_cwd)
    _test_home.cleanup()
