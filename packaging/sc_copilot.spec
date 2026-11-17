import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(ROOT, "App")
INCLUDE_KOKORO = os.environ.get("SC_INCLUDE_KOKORO") == "1"

datas = [(os.path.join(APP, f), ".") for f in ("sc_default_binds.json", "sc_copilot.png", "sc_copilot.ico")]
datas += [(os.path.join(APP, "legal"), "legal")]
datas += collect_data_files("faster_whisper")
datas += collect_data_files("certifi")
binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime")

excludes = ["matplotlib", "pandas", "scipy", "IPython", "pytest", "PyQt5", "PySide6", "torch"]
if not INCLUDE_KOKORO:
    excludes += ["kokoro_onnx", "phonemizer", "espeakng_loader"]

version_file = os.path.join(SPECPATH, "version_info.txt")

a = Analysis(
    [os.path.join(APP, "sc_copilot.pyw")],
    pathex=[APP],
    binaries=binaries,
    datas=datas,
    hiddenimports=["sc_paths", "sc_version", "sc_update", "sc_nvidia", "sc_winicon", "sc_avatar", "edge_tts", "zstandard", "soundfile", "sounddevice"],
    excludes=excludes,
    module_collection_mode={"edge_tts": "py"},
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SC Co-Pilot",
    icon=os.path.join(APP, "sc_copilot.ico"),
    version=version_file if os.path.exists(version_file) else None,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SC Co-Pilot", upx=False)
