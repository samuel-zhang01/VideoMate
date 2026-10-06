"""Build a portable development archive using only the standard library.

Requires Python on the destination. This is not the future self-contained
offline production bundle. No downloads or package installations occur.
"""

import shutil
import tempfile
import zipapp
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / "dist" / "videomate.pyz"
destination.parent.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="videomate-build-") as temporary:
    stage = Path(temporary)
    package = stage / "videomate"
    package.mkdir()
    for source in (root / "src" / "videomate").glob("*.py"):
        shutil.copyfile(source, package / source.name)
    shutil.copyfile(root / "schemas" / "diagnostic-export-v1.schema.json", package / "export-schema.json")
    shutil.copyfile(root / "LICENSE", stage / "LICENSE")
    (stage / "__main__.py").write_text("from videomate.cli import main\nraise SystemExit(main())\n", encoding="utf-8")
    zipapp.create_archive(stage, destination, compressed=True)
print("Built dist/videomate.pyz (development archive; Python 3.11+ required).")
