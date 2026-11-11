"""Обёртка пилота: фиксирует корень, ревизию и исключения набора (последний --root/--ref побеждает)."""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHA = "1e085652f6a7a5b3825f87157769be6de47ad928"
EXCLUDE = [
    "scripts/nav_bench",
    "scripts/atlas/tests",
    "docs/handoffs",
    "docs/reports",
    "docs/reviews",
    "plans",
    "docs/claude/memory",
    "docs/claude/OPEN_QUESTIONS.md",
    "multiprocess_framework/modules/process_manager_module/tests",
    "multiprocess_framework/modules/process_manager_module/DECISIONS.md",
    "multiprocess_framework/modules/process_manager_module/STATUS.md",
    "multiprocess_framework/modules/process_module/tests",
    "multiprocess_framework/modules/process_module/DECISIONS.md",
    "multiprocess_framework/modules/process_module/STATUS.md",
    "multiprocess_framework/modules/process_module/README.md",
    "multiprocess_framework/modules/app_module/tests",
    "multiprocess_framework/modules/app_module/DECISIONS.md",
    "multiprocess_framework/modules/app_module/STATUS.md",
    "multiprocess_framework/modules/app_module/README.md",
    "multiprocess_framework/modules/message_module/DECISIONS.md",
    "backend_ctl/tests",
    "backend_ctl/DECISIONS.md",
    "backend_ctl/STATUS.md",
    "backend_ctl/README.md",
    "Plugins/sim/scene_source/tests",
    "Plugins/sim/scene_source/STATUS.md",
    "Services/line_sim/tests",
    "Services/line_sim/DECISIONS.md",
    "Services/line_sim/STATUS.md",
    "Services/device_hub/tests",
    "Services/device_hub/DECISIONS.md",
    "Services/device_hub/STATUS.md",
    "Services/device_hub/README.md",
    "Plugins/processing/word_layout/tests",
    "Plugins/processing/word_layout/STATUS.md",
    "Plugins/processing/word_layout/README.md",
    "multiprocess_prototype/backend/tests",
    "multiprocess_prototype/backend/config/tests",
    "multiprocess_prototype/backend/config/README.md",
    "multiprocess_prototype/domain/tests",
    "multiprocess_prototype/frontend/widgets/tabs/pipeline/tests",
    "multiprocess_prototype/frontend/widgets/tabs/recipes/tests",
    "multiprocess_prototype/frontend/widgets/tabs/services/robot/tests",
]
args = sys.argv[1:]
cmd = [sys.executable, str(HERE / "scripts" / "atlas"), *args, "--ref", SHA, "--root", str(HERE)]
if args and args[0] == "ref":
    cmd += ["--format", "passport"]
for prefix in EXCLUDE:
    cmd += ["--exclude", prefix]
sys.exit(subprocess.run(cmd).returncode)
