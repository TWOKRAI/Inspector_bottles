"""Inspector Bottles — launcher.

Double-click or run from any terminal — auto-detects the correct .venv via uv.

Available targets:
  run.py           — multiprocess_prototype_v3 (default)
  run.py v2        — multiprocess_prototype (legacy)
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "v3": ROOT / "Inspector_prototype" / "multiprocess_prototype_v3" / "main.py",
    "v2": ROOT / "Inspector_prototype" / "multiprocess_prototype" / "main.py",
}
DEFAULT = "v3"

# Expected project .venv python
_EXPECTED_VENV = ROOT / ".venv"


def _running_in_project_venv() -> bool:
    """Check if current interpreter is the project's own .venv."""
    try:
        return Path(sys.prefix).resolve() == _EXPECTED_VENV.resolve()
    except (OSError, ValueError):
        return False


def _relaunch_via_uv() -> int:
    """Re-exec this script through `uv run` so the project .venv is used."""
    uv = shutil.which("uv")
    if not uv:
        print(
            "ERROR: uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/"
        )
        return 1

    # Forward all original argv (target key, etc.)
    cmd = [uv, "run", "--project", str(ROOT), "python", __file__] + sys.argv[1:]
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def main() -> int:
    # If we're NOT inside the project's .venv, relaunch via uv
    if not _running_in_project_venv():
        return _relaunch_via_uv()

    target_key = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in TARGETS else DEFAULT
    target = TARGETS[target_key]

    if not target.exists():
        print(f"Error: {target} not found")
        return 1

    print(f"Launching {target_key}: {target.relative_to(ROOT)}")
    result = subprocess.run([sys.executable, str(target)], cwd=str(ROOT))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
