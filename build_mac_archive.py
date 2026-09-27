"""Package the current portable project and a consistent SQLite snapshot.

The private .env (including the Telegram token) and local binaries are excluded.
"""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
DESTINATION = ROOT.parent / "lavie-beauty-mac.zip"
EXCLUDED_DIRS = {".venv", ".artifacts", "__pycache__", "staticfiles", ".pytest_cache", ".git"}
EXCLUDED_FILES = {".env", "db.sqlite3", "db.sqlite3-shm", "db.sqlite3-wal",
                  "beauty.sqlite3", "beauty.sqlite3-shm", "beauty.sqlite3-wal"}

with tempfile.TemporaryDirectory() as temporary:
    snapshot = Path(temporary) / "beauty.sqlite3"
    with closing(sqlite3.connect(ROOT / "beauty.sqlite3")) as source, closing(sqlite3.connect(snapshot)) as target:
        source.backup(target)
    with ZipFile(DESTINATION, "w", compression=ZIP_DEFLATED) as archive:
        for path in ROOT.rglob("*"):
            if not path.is_file() or any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
                continue
            if path.name in EXCLUDED_FILES or path.suffix in {".pyc", ".log"}:
                continue
            relative = Path("lavie-beauty") / path.relative_to(ROOT)
            if path.name == "start_mac.command":
                info = ZipInfo(str(relative).replace("\\", "/"))
                info.external_attr = 0o100755 << 16
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, path.read_text(encoding="utf-8").replace("\r\n", "\n"))
            else:
                archive.write(path, str(relative).replace("\\", "/"))
        archive.write(snapshot, "lavie-beauty/beauty.sqlite3")

print(DESTINATION)
