---
name: project-venv-locked-by-mcp
description: MCP backend_ctl держит numpy .pyd; Claude Code респавнит его — kill по PID гонку не выигрывает
metadata:
  type: project
---

Переустановка бинарных пакетов (`numpy`, `Pillow`, `cv2`) в этом venv падает с `os error 32 / 5` («файл занят другим процессом»), потому что MCP-сервер `backend_ctl` импортирует фреймворк и держит замапленными `.venv\Lib\site-packages\numpy\_core\_multiarray_umath.pyd` и `numpy\linalg\_umath_linalg.pyd`.

Цепочка процессов: `Code.exe` → `claude.exe` (расширение Claude Code) → `uv run --no-sync -- python -m backend_ctl.mcp_server_sdk` → дочерний `python.exe` (держатель).

**Why:** Claude Code поднимает MCP-сервер заново за миллисекунды после смерти. 2026-07-31 проверено трижды: `Stop-Process -Id ... ; uv pip install ...` одной строкой всё равно проигрывает — сервер возвращается, пока uv готовит колесо. Гонка не выигрывается принципиально, PID меняется каждый раз.

**Цена ошибки:** полуустановленный numpy (py-файлы от 2.5.1, `.pyd` от 2.4.4) даёт `ImportError: cannot import name 'row_stack'`, и вместе с ним падает `cv2` с обманчивым «OpenCV bindings requires numpy» — симптом указывает не на виновника.

**How to apply:** переустановку numpy/Pillow/cv2 делать при **полностью закрытом VS Code**, из отдельного PowerShell. Перед установкой убедиться, что держателей нет:
`Get-Process python -EA SilentlyContinue | Where-Object { $_.Modules.FileName -like '*Inspector_bottles\.venv*' } | Select Id`
Держателя искать по загруженным модулям, а не по имени процесса. См. [[feedback-uv-sync-prunes-venv]], [[feedback-no-global-taskkill]], [[project-cuda-torch-setup]].
