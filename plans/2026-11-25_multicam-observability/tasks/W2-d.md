# Task W2-d: `system_overview` показывает аварию прогона и потерянный источник

- **Статус:** [PENDING] · **Level:** Middle · **Assignee:** developer
- **Module contract:** impl-only (`backend_ctl/overview.py`: два новых вида аномалий в прежнем списке)
- **Dependencies:** W2-a1 (блок `link` камеры), W2-b1 (блок `link` считывателя) — имена ключей; аномалия `run_fault` от них не зависит
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS; радиус `backend_ctl/tests` (medium)
- **Files:** `backend_ctl/overview.py`, `backend_ctl/tests/test_overview_run_and_link.py`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** developer (REDS в брифе, красный прогон до правки src, break-injection) -> reviewer (стадия 5, sonnet)

Основание: инцидент 2026-11-25 11:44 (`docs/reviews/2026-11-25_incident-restart-freeze.md`, worktree `mco-integ`): `system.run.state=fault`, а `system_overview` показывал все процессы `running` без аномалии — диагностика через MCP не навела на причину остановки линии.

TASK: W2-d — две аномалии обзора: `run_fault` и `source_lost`   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: developer
CHAIN: lead -> you -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. В функции обзора, где собирается `anomalies` (`overview.py:136-343`, тот же вид записей `{"kind", "process", "detail"}`): `system.run.state == "fault"` -> `{"kind": "run_fault", "process": "system", "detail": "<причины через '; '>"}`, причины — `reason` из `system.run.last_fault.reasons` (до 5, хвост ` (+N)`), с пометкой ` [квитирована]`, если `acknowledged_at` не пусто.
  2. Для каждого процесса: в state есть блок `link` с `state == "lost"` (камера: `state.plugins.<плагин>.link`; считыватель: `state.code_reader_sdk.link`) -> `{"kind": "source_lost", "process": <процесс>, "detail": f"lost_for_s={…} outages={…}"}` (ключи, которых нет, — пропустить, без исключения).
  3. Источник `system.run` — тот же, которым backend_ctl уже читает состояние прогона (найти `git grep -n "system.run" -- backend_ctl`); новых запросов к PM обзор не делает, если поле уже есть в снимке.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. backend_ctl/overview.py — две аномалии
  2. backend_ctl/tests/test_overview_run_and_link.py — новый, литеральные снимки

REDS (predicted red tests):
  - backend_ctl/tests/test_overview_run_and_link.py::test_run_fault_is_anomaly_with_reason_text (снимок: `fault`, причина «camera_0: перезапускается супервизором» -> аномалия `run_fault`, `detail` содержит литерал)
  - backend_ctl/tests/test_overview_run_and_link.py::test_running_has_no_run_fault
  - backend_ctl/tests/test_overview_run_and_link.py::test_camera_link_lost_is_anomaly
  - backend_ctl/tests/test_overview_run_and_link.py::test_reader_link_lost_is_anomaly
  - backend_ctl/tests/test_overview_run_and_link.py::test_missing_link_block_is_not_error

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short backend_ctl/tests/test_overview_run_and_link.py` -> exit 0
  - радиус `backend_ctl/tests` (medium, `--tb=no -rfE`) -> красные = снимок лида; `ruff check -q` по двум путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short backend_ctl/tests/test_overview_run_and_link.py

OUT OF SCOPE: fps по камерам из levels и остальные аномалии T9; `set_register_verified` с `device_verified`.
TRAPS: если `system.run` в снимке обзора нет и его чтение требует нового запроса к PM — стоп и вопрос лиду (лишний запрос на каждый обзор). Литералы ключей `link` берите из брифов W2-a п.10 и W2-b1 п.4, не из догадок.
HANDOFF IN: W2-a1, W2-b1 — имена ключей блока `link`.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
