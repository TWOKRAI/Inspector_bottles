# Передача: полоса К, фаза 1 плана device-common-base

Дата: 2026-11-26. Для следующего чата камерной полосы.

## Состояние

- Ветка `integ/dcb-phase1`, дерево `.claude/worktrees/k-f1`. В `main` НЕ влита (`main` = `eaaf82a60`).
- H1 (и H1-fix), H2, H3, H4, H5, H9 — готовы, приняты ревью, влиты. Отчёты: `docs/reports/2026-11-26_device-common-base_*.md`.
- C6.1 — готова: два раунда ревью, живой стенд пройден 2026-11-26 (`docs/reports/2026-11-26_device-common-base_C6.1.md`).

## Осталось

2. Перед слиянием, в своём окне (раньше гейт это пропускал): `multiprocess_prototype/domain/tests`,
   `Services/hikvision_camera/tests`, `Services/camera_device/tests`, `scripts/memory` (новый урок в каноне);
   затем rebase, `validate.py`, `multiprocess_prototype/backend/tests`, прогон фреймворка. Каждый красный назвать по
   `plans/queue/defects.md`. Известный старый: `test_catalog_kind_roundtrip` (нет `robot_io.forward_ok`,
   `robot_io.last_dropped_job` в снимке).
3. Слияние в `main` — только по слову владельца, `merge-begin` / `merge-end`. Первое слияние приносит и сам план.

## Открыто (вне задач фазы 1, никто не чинит)

- Камера: отключение между `take_device` и `session.start` отвечает `ok/idle`, а кадры идут (`plugin_base.py:975-1034`);
  воспроизведено при принудительном чередовании.
- `Services/device_hub/drivers/hikvision_driver.py:67-83`: `connect()` -> True при неудачном `open` (передано координатору).
- `mvcr_probe.py` `_restore`: при мёртвом stdout восстанавливается только первый узел.
- Hikvision: поле `driver` перезаписывается конфигом, порт всё равно `mvs`; `source_type="simulator"` (F5) не исправлен.
- `frame_watch` не сбрасывается при `lost -> grabbing` (по чтению).
- Панель плашки читает сырой файл: `plate_text: 5` показывает «5», загрузчик пишет «взят » (`recipe_displays.py:255,270`).
- Для H8: `PYTHONUTF8=1`, момент вставки кабеля записывать отдельно. Для H6: начинает ли MVS номера заново после перезахвата.

## Окружение и отказы

- `protect-branch.sh` берёт ветку из каталога сессии: коммит агента из worktree отклоняется («main»), а строки, начинающиеся
  не с `git commit`, хук не проверяет. Коммит правки H2 лид сделал по слову владельца.
- `pre_report_gate` в worktree красный (`pytest` не импортируется) и советует `uv sync` — не выполнять.
- Auto mode отклонял скрипты, переписывающие исходник ради инъекции. Инъекции — подменой в памяти. Один ревьюер после
  отказа выполнил те же шаги по частям (деревья чистые) — владельцу сказано.
- Матрица инъекций — класс `heavy`; в этой сессии гонялась как `light`, в том числе в чужом stand-окне (сказано координатору).

## agentId

| задача | исполнитель | ревьюер |
|---|---|---|
| брифы | — | `a4c81bfc440fae244` |
| C6.1 | `ad1c30123e875c8bc` | `ae3c20f49b46c5961` |
| H1 | — | `ae683b41573170a3d` |
| H2 | `a747de6c41b0b03a8` | `a887e583c9874eef6` |
| H3 + H1-fix | `ac9d1d40d3ed441db` | `a5880605126c8f9ab` |
| H4 | `a829d384a83f4947b` | `a13df50f46ccb0119` |
| H5 | `a990a5440d5a349ac` | `a4235fe5e98846a52` |
| H9 | `a33531db02ea423dc` | `a8cc3c5248ff7891a` |
