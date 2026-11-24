---
name: project_py312_torch212_cu132_stack
description: "Решение владельца 2026-11-23: общий стек Windows + Jetson Orin NX 16GB — Python 3.12, torch 2.12.0, torchvision 0.27.0, cu132, JetPack 7.2.2; Python 3.14 отложен, chore/deps-py314 не сливать"
mechanism: [windows-env, architecture]
metadata:
  type: project
---

Единая связка для Windows (RTX 3050) и боевой машины Jetson Orin NX 16 ГБ: **Python 3.12, torch 2.12.0, torchvision 0.27.0, CUDA build cu132, JetPack 7.2.2** (Jetson Linux 39.2.2, Ubuntu 24.04, glibc 2.39, CUDA 13.2.2). Решение владельца, 2026-11-23, после анализа полосы Т.

**Why:** Python 3.14 с CUDA-torch на Jetson не подтверждён ни одним источником (NVIDIA собирает колёса под системный Python, на JP 7 это 3.12); torch 2.12.0 на Orin проверен сотрудником NVIDIA (Orin Nano, форум 2026-06-10) и сообществом (Orin NX 16 ГБ). JetPack 6 не подходит: Python 3.10, у torch 2.15 нет CUDA 12.6, колесо PySide6 6.12 для aarch64 требует glibc 2.39 (`manylinux_2_39`), а у JetPack 6 он старше.

**How to apply:**
- Ветка `chore/deps-py314` (`requires-python >=3.14`, `torch>=2.15`) не сливается; сравнение 3.12 / 3.14 на Windows отменено владельцем, venv и worktree `Inspector_bottles--py314` удалены. Обновить библиотеки (PySide6 6.12, numpy 2.5, opencv 5.1) можно и на 3.12, отдельной проверкой.
- torch на JetPack 7.2: индекс `https://download.pytorch.org/whl/cu132` (NVIDIA, форум 2026-06-10: «Orin can use SBSA package now»); не `uv sync` вслепую ([[feedback_uv_sync_prunes_venv]]).
- Не проверено на железе: `torch.cuda.get_arch_list()` на sm_87 (NVIDIA говорит «работает», сообщество — «в колесе нет sm_87»), Qt/PySide6 на Jetson (eglfs/xcb), CUDA-вариант onnxruntime-gpu для Orin, TensorRT 11.4.1 вместо 10.x в JP 7.2.2 (движки `.plan`/`.engine` придётся пересобрать). Проверять на плате.
- Windows ПРОВЕРЕНО 2026-11-23: драйвер 595.95, `torch 2.12.0+cu132` / `torchvision 0.27.0+cu132` в `.venv` — `cuda.is_available()=True`, RTX 3050 (sm_86), matmul и mobilenet_v3 на GPU работают, `pip check` чистый. Ставить ТОЛЬКО `--index-url .../whl/cu132` без PyPI рядом: с `--extra-index-url` uv берёт CPU-колесо. `torch.cuda.get_arch_list()` на x86: sm_75/80/86/90/100/120, sm_87 (Orin) нет — на плате работает ли через sm_80-кубин, не проверено. См. [[project_cuda_torch_setup]], [[project_hardware_roles_2026_09_23]].
