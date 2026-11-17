import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App"))
import sc_version as VER  # noqa: E402

nums = [int(n) for n in re.findall(r"\d+", VER.VERSION)[:3]]
nums += [0] * (4 - len(nums))
t = tuple(nums[:4])

text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'mattboy112'),
      StringStruct('FileDescription', 'SC Co-Pilot'),
      StringStruct('FileVersion', '{VER.VERSION}'),
      StringStruct('InternalName', 'SC Co-Pilot'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 mattboy112. Unofficial fan tool, not affiliated with Cloud Imperium Games.'),
      StringStruct('OriginalFilename', 'SC Co-Pilot.exe'),
      StringStruct('ProductName', 'SC Co-Pilot'),
      StringStruct('ProductVersion', '{VER.VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
(Path(__file__).resolve().parent / "version_info.txt").write_text(text, encoding="utf-8")
print(VER.VERSION)
