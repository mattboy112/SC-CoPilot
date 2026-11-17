import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App"))
import sc_version as VER  # noqa: E402

text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
m = re.search(rf"^## \[?v?{re.escape(VER.VERSION)}\]?.*?$(.*?)(?=^## |\Z)", text, re.S | re.M)
notes = (m.group(1).strip() if m else f"SC Co-Pilot {VER.VERSION}")
notes += ("\n\n---\n**Install:** download `SC_CoPilot_Setup_" + VER.VERSION + ".exe` below and run it. "
          "Windows may say it protected your PC because the installer isn't code-signed yet: click **More info → Run anyway**.\n\n"
          "Unofficial fan tool. Not affiliated with Cloud Imperium Games.")
(ROOT / "release_notes.md").write_text(notes, encoding="utf-8")
print(notes)
