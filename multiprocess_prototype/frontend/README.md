# frontend — GUI-пакет прототипа

> Обновлено: 2026-07-18 (Ф2 frontend-constructor — граница фронт/бэк)

## Что это

Qt-презентация (PySide6) поверх бэкенда прототипа. До Ф2 GUI-процесс был частью
обязательного фундамента (`backend/topology/base.yaml`) — бэкенд не мог стартовать
«без объявления фронта». Ф2 (`plans/frontend-constructor/plan.md`) развёл границу:
бэкенд по умолчанию headless, фронт — отдельная точка входа.

## Как запустить фронт отдельно

```bash
python multiprocess_prototype/frontend/run.py
```

Это тот же бэкенд (`main.main()`), что и обычный вход (`multiprocess_prototype/run.py`),
но с включённым презентационным overlay: `frontend/run.py` выставляет
`INSPECTOR_PRESENTATION=<путь к frontend/presentation.yaml>` ДО вызова `main()`.
`backend/config/manifest.py::load_manifest` читает этот env-overlay так же, как
`INSPECTOR_MANIFEST` для пути к самому манифесту — приоритетнее значения из `app.yaml`
(который presentation не задаёт, headless по умолчанию).

Headless-флаг перебивает presentation, даже поднятый через `frontend/run.py`:

```bash
python multiprocess_prototype/frontend/run.py --headless
```

## Что такое «хардкод-shell»

Это НЕ generic-конструктор фронта — фронт остаётся тонкой прошитой оболочкой
прототипа (см. `plans/proto-frontend-carve.md`, раздел «Что "хардкод-shell" значит
на практике»):

- презентационный overlay — фиксированный файл (`presentation.yaml`), не собирается
  динамически;
- точка входа (`run.py`) — явный скрипт с прошитым выбором overlay, не параметризуемая
  фабрика;
- фронт по-прежнему **форвард-импортит** сборку бэкенда (`backend.launch`,
  `backend.config`, `backend.state`) — это допустимо и ожидаемо на этом шаге;
- GUI по-прежнему спавнится ТЕМ ЖЕ launcher'ом (через overlay в топологии), а не
  отдельным ОС-процессом, аттачащимся к уже живому бэкенду.

Ценность — в структурной развязке: обязательный фундамент бэкенда больше не знает
про фронт (`base.yaml` — только always-on инфра), граница закреплена
sentrux-инвариантом (`backend/* → frontend/* forbid`), а точка входа фронта отделена.
Этого достаточно, чтобы конструктор фронта (В3, `plans/frontend-constructor/plan.md`
Ф3+) начал строиться поверх, не распутывая композицию заново.

## Презентационный overlay (`presentation.yaml`)

Единственный процесс `gui` (`process_class:
multiprocess_prototype.frontend.process.GuiProcess`, `protected: true`). Подмешивается
`SystemBuilder.from_manifest` ПЕРЕД pipeline: `merged = base ⊕ presentation ⊕ pipeline`.

**Известный edge case (вне скоупа Ф2):** несколько рецептов (`phone_sketch`,
`hikvision_letter_robot`, `dataset_circle_capture`, `camera_robot_calibration`,
`letter_angle_inspect`, `webcam_sketch`) объявляют процесс `gui` ИНЛАЙН прямо в себе
(GUI-редактор сохранял топологию целиком, включая презентацию). При запуске БЕЗ
presentation-overlay они всё равно поднимут GUI — рецепт несёт его сам. Это ожидаемо,
не баг headless-режима; реконсиляция — после стабилизации recipe-оси (C3/4.7,
`plans/proto-frontend-carve.md`, риск №1).

Для recipes с инлайн-`gui` порядок процессов в собранной топологии тоже отличается
от «чистых» pipeline-топологий: раньше `gui`+`devices` фундамента всегда шли первыми
(дедуп поглощал инлайн-копии рецепта); теперь, когда `base.yaml` не объявляет `gui`,
инлайн-`gui` рецепта проходит через merge не дедуплицируясь с фундаментом — содержимое
процесса (класс/protected/plugins) идентично, но порядок в списке процессов
(`process_names`) может отличаться от предыдущих golden-снапшотов
(`backend/tests/snapshots/*.build.json`) для этих двух живых рецептов.

## Отложенное (эстафета в конструктор фронта, В3)

- **Dual-launcher runtime-аттач** — фронт как отдельный ОС-процесс, аттачащийся к уже
  живому бэкенду через сокет (не через общий launcher). Причины отложить: (а) владелец
  сказал «пока хардкодом»; (б) грабли «два бэкенда в одном прогоне» — общий PID-реестр
  и SHM-cleanup конфликтуют между параллельными системами (см. память
  `project_concurrent_backends_trap`).
- **Сокращение forward-импортов `frontend → backend`** — `frontend/app.py` тянет
  `backend.launch/config/state/recipes`; разбор на IPC-only контракт — работа
  конструктора.
- **Recipe-инлайн `gui`** (5-6 рецептов) — реконсиляция после C3/4.7.
- **DX-регресс промоушенов** (Ф3+ плана frontend-constructor): виджеты/формы,
  вынесенные во framework, перестанут подхватываться hot-reload'ом прототипа
  (purge-зона — только `multiprocess_prototype.frontend.*`).

## Связанные документы

- [`plans/frontend-constructor/plan.md`](../../plans/frontend-constructor/plan.md) — Ф2
  (граница фронт/бэк), далее Ф3+ (промоушен генерик-кита во framework).
- [`plans/proto-frontend-carve.md`](../../plans/proto-frontend-carve.md) — справочная
  спецификация задач Ф2 (детальные Task 0.1/1.1/1.2/2.1/2.2/3.1).
- [`../STATUS.md`](../STATUS.md) — раздел «Граница фронт/бэк».
