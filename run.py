"""Inspector Bottles — launcher (router).

Delegates to the run.py inside the selected prototype folder.

Available targets:
  run.py           — multiprocess_prototype_v3 (default)
  run.py v2        — multiprocess_prototype_v2
  run.py v1        — multiprocess_prototype (legacy)
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROTO = ROOT / "Inspector_prototype"
TARGETS = {
    "v3": PROTO / "multiprocess_prototype_v3" / "run.py",
    "v2": PROTO / "multiprocess_prototype_v2" / "run.py",
    "v1": PROTO / "multiprocess_prototype" / "run.py",
}
DEFAULT = "v3"


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
