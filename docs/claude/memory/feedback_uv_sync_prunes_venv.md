---
name: feedback-uv-sync-prunes-venv
description: uv sync сносит всё, чего нет в pyproject — в этом venv ходить только через --inexact
metadata:
  type: feedback
---

`uv sync` приводит venv в **точное** соответствие локу: всё, поставленное руками через `uv pip install`, для него мусор и удаляется молча. 2026-07-31 команда `uv sync --group diagrams` (взята из CLAUDE.md как «установка диаграмм») снесла **27 пакетов** — `torch 2.6.0+cu124`, `torchvision`, `onnxruntime`, `onnx`, `pymodbus`, `mediapipe`, `timm`, `segno`. Восстановление заняло ~час и сломало venv по дороге.

**Why:** в этом проекте критичная часть окружения принципиально не выражается через `pyproject.toml` — CUDA-колесо torch живёт на стороннем индексе (см. [[project-cuda-torch-setup]]), а `mediapipe`/`segno` импортируются в коде, но в зависимостях не объявлены. Для `uv sync` они неотличимы от случайного хлама.

**Самая злая ловушка — cv2.** `opencv-python` (объявлен) и `opencv-contrib-python` (приходит транзитивно с mediapipe) кладут файлы в **один каталог `cv2/`**. Удаление contrib стирает каталог целиком, а `opencv_python-*.dist-info` остаётся — uv считает opencv установленным и обычным sync'ом это не чинит. Нужен явный `--reinstall`, либо возврат mediapipe.

**How to apply:** в этом venv всегда `uv sync --inexact` — он не трогает необъявленное. Перед любым обычным sync знать поимённо, что стоит руками. Правильное лечение — объявить `mediapipe`/`segno` в extras, а torch честно оставить вне sync. Установки запускает пользователь ([[feedback-package-install-by-user]]); переустановка бинарных пакетов требует закрытого VS Code ([[project-venv-locked-by-mcp]]).
