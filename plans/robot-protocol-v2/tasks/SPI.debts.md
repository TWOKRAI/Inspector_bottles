# SPI хаба — долги из плана: сверка с git (база main `9b6645546`)

Бриф — `tasks/SPI.md`. Строка плана — `plan.md:302`. Редакция 2 (после стадии 0 р.1, `tasks/SPI.stage0.md`).

| # | Долг | Статус | Доказательство |
|---|---|---|---|
| 1 | Оракул `_LATCH_ROWS` без переходов T5.3g | **открыт** → SPI.a | `test_robot_v2_state_acceptance.py:804-826`: 20 строк; нет `connect_begin`, `connect_link_up`, `connect_restore`, `connect_finish`, `connect_end`, `set_ready` (коммит T5.3g `d4220d24a`), нет `connect_check`, `is_shutdown`, `disconnect_stop_plan` (T5.3f). Публичных методов `RobotState` — 63 (AST, стадия 0 п.11). До `_latch_reset_locked` (`state.py:191`) доходят 7: `admit_launch`, `connect_begin`, `connect_reset`, `disconnect_begin`, `jog_started`, `request_stop_begin`, `take_next_action`; в оракуле со сбросом — 6 (нет `connect_begin`: исход `"go"` → `_connect_reset_locked`, `state.py:300`, :268-271). Теста полноты нет. |
| 2 | Шов `_client`: хаб без приватного состояния драйвера | **открыт** → SPI.b2 (прод), SPI.f (тесты) | Прод: `manager.py:564`, `:597` — `getattr(driver, "transport", None) or driver._client`; у `VfdDriver` нет ни `transport`, ни `_client` (`vfd_driver.py:48` — `_vfd_client`), `device_read` ПЧ отвечает текстом `AttributeError`. Тесты: `git grep -nE '\._client\b' -- Services/device_hub/tests Plugins/hub/device_hub/tests` → 59 строк; из них 16 в `test_robot_driver.py` (13) и `test_vfd_driver.py` (3) — свои клиенты v1/ПЧ, остаются; 43 — драйвер v2 (6 присваиваний `._client =`). Сторож считает 40 (`_SEAMS["_client"]`, `test_no_private_driver_state.py:82`) — счёт задачи по `git grep`, не по сторожу. |
| 3 | `request_disconnect`, `disconnect_pending` в контракте драйвера | **открыт** → SPI.b1/b2 | `plugin.py:912` (`getattr(driver, "request_disconnect", None)`), `plugin.py:446`, `manager.py:425` (`getattr(driver, "disconnect_pending", False) is True`); `driver.py:298-300` называет долг. Контракта нет: `base.py:33-131` — только базовый класс. |
| 4 | `disconnect_pending` в `_COMMON_NAMES` сторожа | **закрыт C-29** | `test_no_private_driver_state.py:98-100`. SPI это имя не удаляет. |

## Счёт обращений к драйверу через `getattr` / `hasattr` (база)

`git grep -nE '(getattr|hasattr)\((driver|drv|dep_driver), "' -- Services/device_hub/manager.py Plugins/hub/device_hub/plugin.py`
→ 13 строк: `plugin.py:368, 372, 446, 454, 551, 553, 562, 912`; `manager.py:131, 425, 453, 564, 597` (подтверждено стадией 0).
Цель после SPI.b2: **0** (решение лида 2026-10-26, включая `request_stop` — флаг способности `stop_aware`).
Вне менеджера и плагина остаются (вне SPI, Out of scope): `vfd_driver.py:332, 334` (`getattr(carrier, "mode" / "busy")` —
атрибуты носителя v1), `transports.py:125, 133`.
