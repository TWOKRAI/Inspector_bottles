---
name: transitive-gui-backend-poisons-the-test-process
description: "matplotlib при живом PySide6 резолвит qtagg — мина в тестовом процессе; в деле AV 2026-08-12 оказалась НЕ причиной (проба: matplotlib в гейте не импортируется)"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 6348ff14-f481-4817-9c8c-a5b9da20bd25
  modified: 2026-08-11T20:19:15.872Z
---

Мина реальна: при установленном PySide6 matplotlib резолвит backend `qtagg`
(факт: `python -c "import matplotlib; print(matplotlib.get_backend())"`), и первый
же транзитивный импортёр (ultralytics-плоттинг и т.п.) молча создаст в тестовом
процессе QApplication и Qt-объекты вне qtbot-дисциплины. Но в расследовании AV
2026-08-12 эта мина оказалась **не взорвавшейся**: session-end проба показала, что
за весь гейт matplotlib не импортируется ни разу, qapp создают frontend-тесты
(штатный qtbot), а падение остановила чистка утечек ([[thread-target-pins-its-owner]]).
Первая атрибуция «это matplotlib» держалась на негодном дискриминаторе —
см. [[discriminator-switch-must-be-verified]].

**Why:** внепроцессный факт («qtagg резолвится») не переносится в процесс прогона
без пробы «а импортируется ли он там вообще»; правдоподобное ≠ проверенное.

**How to apply:** в корневом conftest прогона держать
`os.environ.setdefault("MPLBACKEND", "Agg")` как страховку класса (интерактивный
backend прогону не нужен нигде), с честным комментарием «сегодня инертна, проверено
пробой». Утверждать её причинность нельзя, пока проба не покажет живой импорт.
Досье: `docs/sessions/2026-08-12_access_violation.md`.
