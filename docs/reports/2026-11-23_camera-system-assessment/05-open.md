# Что я оставил открытым или ненадёжно

Часть отчёта [README.md](README.md).

- Каталоги тестов целиком не прогнаны: гейт ответил `STAND WINDOW — skipped`, exit 75. Мой прогон — 2 файла, 24 passed. Это не доказательство гарантий ядра.
- Стенд 2026-11-23 я не видел. Цифры 24,97 Гц и перезахват — из брифа и `OPEN_QUESTIONS.md:2622`. Это незакоммиченная правка чужой сессии.
- Счёт 12 уровней — по чтению кода. Внутрь `RegistersManager.set_field_value` и обёртки `MvCamera` я не спускался; число может отличаться на 1–2.
- Подключает ли хаб запись kind `hikvision` сам и есть ли она в `devices.yaml` стенда — не проверено. От этого зависит тяжесть [слабого места 1](02-weaknesses.md).
- Возвращает ли `HikvisionCamera.open` отказ без исключения (тогда F1 из `plan/design.md:46` жив) — не проверено.
- Что ни один рецепт не выбирает бэкенд `camera_service` `hikvision` — взято из `docs/design/camera-device-architecture.md` §2.4, не перепроверено.
- По чтению `plugin_base.py:402-406` и `:526-548` кадр, вытесненный из слота, не попадает в `dropped`. Потерю видно только по разрывам `seq_id`. Не воспроизведено; поэтому это гипотеза, не дефект.
- Делает ли GUI проверку провода по `Port dtype` базы (`image/gray`) — не проверял.
- Итог опыта 0.5 по H1 (умолчание `restart_regrab` для MVS) я в прочитанных документах не нашёл. Возможно, он записан в `tasks/0.5.result.md` или отчёте 0.5 — их я не читал.
- М2 по 6.3: закрыта ли веха, по дереву решить нельзя (см. [г2](04-discrepancies.md#г-вехи-м1м3-и-приоритеты-p1p2)).
- Инвентарь (48 и 14 строк импорта, строки кода и тестов, 365 и 219 `def test_`) собрал помощник Haiku. Решающие строки я прочёл сам: `driver.py`, `plugin.py`, `__init__.py`, `controller.py`, `presenter.py:97-109`, `hikvision_driver.py:64-83`, вывод grep `check_bindings`. Числа инвентаря я не пересчитывал.
- Цитаты карточек arch-review помощник склеил из окон grep; побайтно я их не сверял.
- Второй помощник Haiku прочёл документы плана целиком, но до меня дошла только сводка без цитат. Все цитаты в [04-discrepancies.md](04-discrepancies.md) я взял сам: `Read` или `Grep -n` по указанной строке.
- Mermaid: все 6 диаграмм прошли рендер Mermaid Chart (`valid: true`) до разбиения отчёта; текст блоков при разбиении не менялся. Обрезку подписей на картинке я глазами не проверял.
- Баллы и координаты рисков — моё суждение по коду и чужим отчётам. Ни один балл не подтверждён стендом, который видел я.
- Вопросы, которые переживут эту задачу (место для `OPEN_QUESTIONS.md`, файл я не правил по брифу): подключает ли хаб kind `hikvision` сам; какое умолчание `restart_regrab` для MVS дал опыт H1; кто и когда закрывает путь `core/*`; закрыта ли М2.

## Какие документы прочитаны

Прочитаны мной целиком:
- `docs/design/camera-device-architecture.md`, `Services/camera_device/{README,STATUS}.md`.
- `Services/camera_device/{interface,session,profiles,params,plugin_base,registers_base,commands}.py`.
- `Services/hikvision_camera/{driver.py,plugin/plugin.py,plugin/registers.py,__init__.py}`.
- `plans/2026-10-18_camera-device-service/{plan,decisions,design}.md`.
- `multiprocess_prototype/frontend/widgets/tabs/services/hikvision/controller.py`.

Прочитаны мной частично — `Grep -n` по темам или первые строки:
- `docs/design/camera-device-service.md` — реестр, зеркало, `live_write`, `restart_regrab`, М2.
- `Services/camera_device/DECISIONS.md` — заголовки ADR, ADR-CAM-001 о реестре.
- `Services/hikvision_camera/README.md` — заголовки, классы, команды.
- `Services/hikvision_camera/DECISIONS.md` — ADR-HIK-001, FROZEN.
- `Services/hikvision_camera/STATUS.md` — строки 1-12.
- `plans/.../matrix.md` — строки 4.2b, 5.1, 4.6.
- `plans/.../amendments.md` — М1–М3, 4.2b, реестр.
- `plans/.../tasks/4.2b.md` — `core`, `HikvisionCamera`, `shell`, FROZEN.
- `plans/.../tasks/5.1.md` — `drivers/__init__`, `create_port`, `driver:`.
- `Services/hikvision_camera/service.py` и `Services/device_hub/drivers/hikvision_driver.py:64-83`.

Прочитаны только помощником Haiku (до меня дошли выдержки):
- Страница `camera-service_artifact_2026-11-17.html`.
- Карточки arch-review.
- Отчёты `2026-11-22_camera-device-service_W4.md` и `2026-11-22_camera-W4-stand.md`.

Не прочитаны:
- `testing/fake_port.py` целиком.
- `plans/.../{wave-protocol,recording-schema,checklist-0.5}.md`.
- `tasks/0.5*.md`, `tasks/4.2a.md`.
- Неотслеживаемые `tasks/4.2d.md`, `tasks/4.2e.md` и `docs/reviews/2026-11-23_plan-camera-device-service_task-4.2d-stage0.md`.
- ADR-CAM-002…006 целиком.
