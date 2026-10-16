# PyInstaller build for the tiqr executable: uv run pyinstaller packaging/tiqr.spec --noconfirm
# PyInstaller cannot cross-compile, so run this on each platform to get its executable in dist/.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "tiqr_entry.py")],
    # Every workspace member's source root; tiqr is a namespace shared across them.
    pathex=[str(path) for path in sorted((ROOT / "apps").glob("*/src"))],
    # Assets are loaded through importlib.resources, so they must ship as data files. The web
    # build, when present, is the api package's data; its version comes from its metadata.
    datas=collect_data_files("tiqr.core")
    + collect_data_files("tiqr.api")
    + collect_data_files("tzdata")
    + copy_metadata("tiqr-api"),
    # `tiqr serve` imports the api on demand, and Uvicorn picks its protocols by name.
    hiddenimports=collect_submodules("tiqr.api")
    + collect_submodules("uvicorn", filter=lambda name: not name.startswith("uvicorn.workers")),
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
