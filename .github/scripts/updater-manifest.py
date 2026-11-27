"""Write latest.json, which the installed Windows app reads to find and verify its next version.

Usage: updater-manifest.py VERSION DIR BASE_URL > latest.json
DIR holds the renamed installers and their .sig files (signed with the updater key in CI).
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

version, folder, base = sys.argv[1], Path(sys.argv[2]), sys.argv[3].rstrip("/")


def entry(name: str) -> dict:
    return {"signature": (folder / f"{name}.sig").read_text(encoding="utf-8").strip(), "url": f"{base}/{name}"}


setup = entry(f"saxs-team-hub-windows-{version}-setup.exe")
platforms = {"windows-x86_64": setup, "windows-x86_64-nsis": setup}
if (folder / f"saxs-team-hub-windows-{version}.msi.sig").exists():
    platforms["windows-x86_64-msi"] = entry(f"saxs-team-hub-windows-{version}.msi")

json.dump(
    {
        "version": version,
        "notes": f"Team Hub {version}. See the release notes on GitHub.",
        "pub_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": platforms,
    },
    sys.stdout,
    indent=2,
)
print()
