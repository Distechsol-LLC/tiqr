# PyInstaller build for the tiqr executable: uv run pyinstaller packaging/tiqr.spec --noconfirm
# PyInstaller cannot cross-compile, so run this on each platform to get its executable in dist/.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "tiqr_entry.py")],
    pathex=[str(ROOT / "src")],
    # Assets are loaded through importlib.resources, so they must ship as data files.
    datas=collect_data_files("tiqr") + collect_data_files("tzdata"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="tiqr",
    console=True,
    upx=False,
)
