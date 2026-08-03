---
name: project-cuda-torch-setup
description: Стенд RTX 3050 4GB; torch для ml_train должен быть cu124-колесом, не +cpu
metadata:
  type: project
---

Стенд обучения: **NVIDIA RTX 3050 Laptop, 4 ГБ VRAM**, драйвер 561.09 (CUDA 12.6), bf16 поддерживается.

GPU есть, но `[ml-train]` ставит torch с дефолтного PyPI → на Windows это всегда `+cpu` (`cuda.is_available()=False`). Лечится переустановкой cu124-колеса:

```
uv pip install --reinstall torch torchvision --index https://download.pytorch.org/whl/cu124
```

cu124-индекс отдаёт `torch 2.6.0+cu124` / `torchvision 0.21.0+cu124` (ниже `torch>=2.11` из pyproject, но работает). AMP идёт в bf16 (Ampere). На 4 ГБ для mobilenet_v3_large @128px ставить `batch_size: 32` (64 → риск OOM при ~2 ГБ занятых дисплеем).

**Грабли:** `uv sync` не просто откатывает torch на `+cpu` — он **удаляет его вместе со всем необъявленным** (2026-07-31: 27 пакетов за один запуск, см. [[feedback-uv-sync-prunes-venv]]). Ходить только через `uv sync --inexact`. Если нужна стойкость — прописать torch с cu124-индексом в `[tool.uv.index]`/`[tool.uv.sources]`. **Переустановка любого бинарного пакета (`Pillow`, `numpy`, `cv2`) падает с «Отказано в доступе» / `os error 32`, если файл держит живой Python-процесс — и это не только прототип/REPL, но и MCP-серверы Claude Code, которые респавнятся сами: [[project-venv-locked-by-mcp]]. Лечится закрытием VS Code, не убийством по PID.** См. [[feedback-package-install-by-user]], [[project-ml-train-service]], [[project-dataset-gen-service]].
