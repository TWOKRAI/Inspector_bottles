# Handoff dev-transport-3: правки ревью 4.7d-2 и 4.7d-3 (transport-single-policy)

Ветка `feat/t47d`, worktree `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles--team-t47d`. План: `plans/transport-single-policy/task-4.7.md`, раздел 4.7d.
Предыдущие хендоффы: `docs/handoffs/2026-10-02_t47d-dev-transport.md`, `..._dev-transport-2.md`, `..._t47d-lead.md`.

## 1. Сделано
- `2496f229a` — правки 1–8 по ревью 4.7d-2a/2b. Принято лидом (10 инъекций убили все).
- `e5fa89edc` — 4.7d-3, дверь отправителя. Слепые `test_t47d3_door.py` (20) и `test_t47d3_wiring.py` (5) зелёные без правок.

## 2. Что в коде (4.7d-3), `frame_shm_middleware.py` (CRLF-файл)
- Конструктор `overflow` (ValueError вне latest|every) + свойство `overflow`.
- `door_drops += 1` — в `strip_and_write` (~:1162), в момент, когда впервые ставится `_shm_dropped`. Под `_bytes_lock`.
- `strip_data_frame_on_send` (~:1214-1218): под every `build_marker(data, reason="door", source=self._owner)`, затем `data.clear(); data.update(marker)` — замена на месте; `not_inspected_door += 1` там же. latest и `_last_loan_exhausted` — `None`.
- `router_manager.get_shm_stats` (:1805-1808): `door_drops` всегда; `not_inspected_door` только если у какого-то middleware `overflow == "every"` (у роутера своего overflow нет). `generic_process.py:231` передаёт `overflow`.
- Тесты: `test_shm_stats_narrow.py` (+ключ `door_drops`), `test_t47d3_author.py` (8). Автор-файл импортирует стенд и фикстуры (`made`, `_received`, `_door_drop_item`...) из слепого `test_t47d3_door.py` — если слепой файл переименуют, сломается.

## 3. Ловушки
- Файлы с CRLF (`frame_shm_middleware`, `router_manager`, `generic_process`, `test_shm_stats_narrow`, `data_receiver`): править скриптом с `newline=""` и `.replace("\n", nl)`. Python в `bash` читает по умолчанию cp1251 — всегда `encoding="utf-8"`. Heredoc в `/tmp` для bash и Python — разные папки; писать в `C:/Users/INNOTECH/AppData/Local/Temp`.
- `git checkout --` заблокирован; откат — правкой файла.
- Команда прогона: `PY=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe; PYTHONPATH="$PWD" "$PY" -m pytest multiprocess_framework/modules/process_module/tests multiprocess_framework/modules/router_module/tests Plugins/control/robot_control/tests -q --tb=no -p no:cacheprovider` -> 3 failed (`test_socket_channel_hol_*`, не наши), 3939 passed, 1 xfailed.
- Стоп-хук `subagent-stop-gate` падает на «No module named pytest» (системный python в worktree, `uv sync` запрещён). Это среда, не код.

## 4. Не сделано / вопросы
- 4.7d-4 (каталог метрик, 449) и 4.7d-5 (стенд, A/B, ADR + `scripts.sync`, README/STATUS, `TEMPLATE.yaml`) — не начаты.
- Для CTO: ведомость исходов на узле-исполнителе; потолок склейки маркеров.
- Дверь: маркер несёт только поля `build_marker` (trace_id, capture_ts, frame_id, camera_id) — `sender`/`timestamp` item'а в маркере нет, у читателя берутся из msg.
- Не мерил: цену `build_marker` + `clear/update` на дропе; живой стенд не гонял.

SHA: `e5fa89edc`. Незакоммиченное чужое: `docs/claude/pilot-company-v2.md` (лид).
