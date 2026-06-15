---
name: feedback-package-install-by-user
description: Установку пакетов (pip/uv pip) запускает пользователь, не агент
metadata:
  type: feedback
---

Установку/переустановку зависимостей запускает **пользователь сам**, агент не вызывает install.

**Why:** в settings есть deny-правило `Bash(python -m pip install*)`; при попытке агента выполнить `uv pip install` пользователь прервал и запустил команду вручную.

**How to apply:** когда нужно (пере)ставить torch/зависимости — выдать пользователю точную команду (для uv-venv: `uv pip install ...`, т.к. `python -m pip` отсутствует — «No module named pip») и ждать подтверждения, что встало. Не запускать install-команды самому. Проверки (`python -c "import torch; ..."`) и обучение в фоне — запускать можно. См. [[project-cuda-torch-setup]], [[feedback-always-project-venv]].
