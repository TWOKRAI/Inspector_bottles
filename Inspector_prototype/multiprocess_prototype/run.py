"""multiprocess_prototype — launcher.

Double-click or run from any terminal — auto-detects the correct .venv via uv.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent.parent  # Inspector_bottles
MAIN = ROOT / "main.py"

_EXPECTED_VENV = PROJECT_ROOT / ".venv"


def _running_in_project_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == _EXPECTED_VENV.resolve()
    except (OSError, ValueError):
        return False


def _relaunch_via_uv() -> int:
    uv = shutil.which("uv")
    if not uv:
        print(
            "ERROR: uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/"
        )
        return 1
    cmd = [uv, "run", "--project", str(PROJECT_ROOT), "python", __file__] + sys.argv[1:]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


def main() -> int:
    if not _running_in_project_venv():
        return _relaunch_via_uv()

    if not MAIN.exists():
        print(f"Error: {MAIN} not found")
        return 1

    print(f"Launching: {MAIN.relative_to(PROJECT_ROOT)}")
    result = subprocess.run([sys.executable, str(MAIN)], cwd=str(PROJECT_ROOT))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
