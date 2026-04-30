"""Inspector Bottles — launcher (router).

Delegates to the run.py inside the selected prototype folder.

Available targets:
  run.py           — multiprocess_prototype (default)
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "v1": ROOT / "multiprocess_prototype" / "run.py",
}
DEFAULT = "v1"


def main() -> int:
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
