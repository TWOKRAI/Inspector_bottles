# -*- coding: utf-8 -*-
"""Образцовый live-тест BCTL-ADR-007 — и урок о том, чего такой тест НЕ доказывает.

Обычный live-тест проверяет «ручка ответила и форма разобралась». Он остаётся зелёным
и на счётчике, навсегда прибитом к нулю: `assert received >= 0` выполняется для мёртвого
счётчика ровно так же, как для живого. Правило BCTL-ADR-007 требует большего — показать
сигнал **отклоняющимся от собственного дефолта**.

**Но у требования есть граница, и этот файл существует главным образом ради неё.**

История написания (оставлена намеренно, она полезнее готового ответа). Первая редакция
мерила `received` у ProcessManager до и после `send_command` и утверждала «наш вызов
подвинул счётчик». Чтение кода показало, что это ложь: `received` инкрементируется только
внутри `receive()`-цикла (`router_manager.py:931-946`), который разбирает то, что вернул
`_poll_all_channels(input_channels_only=True)` — каналы с префиксом `<имя_процесса>_*`.
`SocketChannel` драйвера туда не попадает, его `poll()` — осознанный no-op. Команды
драйвера, адресованные САМОМУ ProcessManager, его `received` не двигают вовсе.

Вторая редакция целилась в дочерний процесс (туда билет доезжает через
`_deliver_by_targets()` и разбирается уже ЕГО `receive()`-циклом) и тоже была зелёной.
Контрольный замер — тест `test_control_background_traffic_also_moves_counters` ниже —
показал, что зелёной она была **не поэтому**: фон живой системы двигает `received`
на ~40 за 3 секунды сам по себе, без единой команды теста. Три наших вызова тонут в этом
фоне полностью.

**Вывод, ради которого файл написан.** У счётчиков router'а на живой системе НЕТ
достижимого плеча OFF: фон нельзя выключить, поэтому «счётчик вырос» здесь доказывает
только «счётчик не заморожен», но НЕ «его двинуло моё действие». Это законный, но слабый
класс доказательства, и называть его атрибуцией — та самая ложь, против которой правило.

Сигнал с ПОЛНОЦЕННОЙ парой ON/OFF выглядит иначе: `ingested_total` (Task 1.2) строго
равен нулю до `watch_like_gui()` и строго больше нуля после — плечо OFF достижимо и
проверяемо. Живой образец — `test_telemetry_driver.py::test_ingest_active_and_ingested_total_live`.
Проектируя новый сигнал, спроси в первую очередь: **достижимо ли для него плечо OFF?**
Если нет — доказательство будет слабым, и это надо признать в докстроке, а не замаскировать.
"""

from __future__ import annotations

import time

import pytest

_PROC = "preprocessor"


@pytest.mark.harness_smoke
class TestSignalLiveness:
    """Счётчики router'а: что про них доказуемо живьём, а что нет."""

    def test_router_counters_are_live_not_frozen(self, headless_backend) -> None:
        """Счётчики ненулевые и растут — то есть подключены к реальности, а не заглушки.

        Что доказано: счётчик не прибит к нулю (главный дефект, ради которого введено
        правило) и форма имён сверена с сервером (`missing == []`).

        Что НЕ доказано: что его двинул именно наш вызов. См. контрольный тест ниже —
        фон двигает его и без нас. Для атрибуции нужен сигнал с достижимым плечом OFF.
        """
        before = headless_backend.router_stats(_PROC, timeout=8.0)
        assert before.ok is True
        assert before.missing == [], f"форма разошлась с сервером: {before.missing}"

        for _ in range(3):
            assert isinstance(headless_backend.introspect_status(_PROC, timeout=8.0), dict)

        after = headless_backend.router_stats(_PROC, timeout=8.0)
        assert after.ok is True
        assert after.missing == [], f"форма разошлась с сервером: {after.missing}"

        assert after.received > 0, "received прибит к нулю — счётчик не подключён к реальности"
        assert after.sent_ok > 0, "sent_ok прибит к нулю — счётчик не подключён к реальности"
        assert after.received > before.received, (
            f"received не растёт вообще: {before.received} -> {after.received} — "
            "счётчик заморожен, что бы ни происходило в системе"
        )

    def test_control_background_traffic_also_moves_counters(self, headless_backend) -> None:
        """КОНТРОЛЬ: тот же замер БЕЗ наших команд. Держит честность теста выше.

        Если этот тест зелёный — фон сам двигает счётчик, и рост в тесте выше
        атрибутировать нашему действию НЕЛЬЗЯ (замерено: ~40 сообщений за 3 c).

        Если он когда-нибудь станет КРАСНЫМ — значит фон затих, плечо OFF стало
        достижимым, и тест выше можно усилить до настоящей атрибуции. То есть этот
        контроль не декорация: он сторожит границу применимости соседнего теста.
        """
        before = headless_backend.router_stats(_PROC, timeout=8.0)
        time.sleep(3.0)  # пауза ВМЕСТО команд — единственное отличие от теста выше
        after = headless_backend.router_stats(_PROC, timeout=8.0)

        assert after.received > before.received, (
            f"фон больше НЕ двигает received ({before.received} -> {after.received}): "
            "плечо OFF стало достижимым — усиль соседний тест до настоящей атрибуции"
        )

    def test_zero_is_a_reading_not_a_gap(self, headless_backend) -> None:
        """Ноль остаётся ЗАКОННЫМ показанием — правило не требует «всё должно быть ненулём».

        `middleware_dropped` на здоровой системе законно равен нулю, и это НЕ повод считать
        сигнал неподключённым: его провенанс доказан отдельно — имя пришло от сервера, иначе
        `missing` его бы назвал. Различение «ноль-показание» и «ноль-заглушка» и есть
        предмет BCTL-ADR-007.
        """
        rs = headless_backend.router_stats(_PROC, timeout=8.0)
        assert rs.ok is True
        assert rs.missing == []
        assert rs.middleware_dropped is not None
        assert rs.middleware_dropped >= 0
