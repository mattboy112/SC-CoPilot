import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SC_COPILOT_HOME", tempfile.mkdtemp(prefix="sc_copilot_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "App"))
