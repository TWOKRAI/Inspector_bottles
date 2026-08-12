---
name: qt-mcp-flag-value-is-compared-verbatim
description: "QT_MCP_PROBE сверяется дословно с «1»; порт — отдельная ручка. Значение «1:9142» промолчало, и рендер GUI не проверялся три раунда"
metadata:
  node_type: memory
  type: feedback
  originSessionId: f967a862-50d7-4012-aa7e-0e9280a4e755
  modified: 2026-08-12T16:54:44.337Z
---

Флаг включается только значением **`QT_MCP_PROBE=1`**. Оба читателя (`qt_mcp_probe.pth` в venv и
`multiprocess_prototype/frontend/app.py`) сравнивают строку с `"1"` дословно; порт частью флага не
является (проба слушает `qt_mcp.probe.DEFAULT_PORT` = 9142).

**Why:** жёсткое ревью 2026-08-12 выставило `QT_MCP_PROBE=1:9142` — «флаг и порт одной ручкой».
Сравнение не совпало, проба не поднялась, и **молча**: `.pth` глушит любое исключение. Следствие
непропорционально причине — рендер GUI-вкладки наблюдаемости не проверялся ни одним из трёх раундов
приёмки F2 и был назван «не проверено никем» в отчёте.

**How to apply:** запуск стенда целиком —
`BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 QT_MCP_PROBE=1 .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py`.
Признак жизни дороги — строка `qt-mcp probe installed on localhost:9142` в `<log_dir>/gui/system.log`
плюс ответ `qt_list_windows`; отсутствие строки теперь WARNING с причиной, а не тишина (Т-2/Т-4
сняли этот «проглоченный сбой»). Класс шире флага: env-ручка, читаемая сравнением с константой,
обязана быть проверена признаком жизни, а не верой в то, что «переменную же выставили».
Связано: [[named-mechanism-is-not-a-commitment]], [[swallowed-failure-class]],
[[gui-stand-production-entry-only]], [[observability-tail-repair]].
