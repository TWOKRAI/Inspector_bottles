# -*- coding: utf-8 -*-
"""Ф8.5 — аудит отдаёт документ в долговечную плоскость.

Резидуалы T2 (Ф5.8) и A2 (Ф5.9): «когда это включили» после рестарта отвечалось grep'ом
по ротируемому журналу, потому что долговечного запрашиваемого следа у аудита не было.
Допуск в стор фреймворка гейтится severity, а аудит пишет INFO/WARNING — ADR-CRM-013.

Сток намеренно структурный (`Callable[[dict], Any]`): фреймворк не имеет права знать про
`Services`. Здесь это же даёт стенд без БД — приёмником выступает список.

Опасности, ради которых тесты и написаны:
  * `__getstate__` выбрасывает непиклимые колбэки. Забыть там `sink` — уронить пиклинг
    ВСЕГО стека слоёв, а он едет в снимок процесса на каждом boot/switch;
  * отказ приёмника не имеет права отменить уже случившуюся смену конфигурации;
  * схлопнутый повтор не должен плодить документы — иначе подметальщик за восемь минут
    насыплет сотню строк в плоскость, заведённую для долгого хранения.
"""

from __future__ import annotations

# pickle здесь безопасен и обязателен: тест round-trip'ит СВОЙ ЖЕ объект, ничего
# внешнего не десериализуя. Проверяется ровно тот механизм, которым фреймворк везёт
# стек слоёв в снимок процесса (`__getstate__`/`__setstate__`), — заменить его на JSON
# значило бы проверять не тот путь.
import pickle  # nosec B403
from typing import Any, Dict, List

from multiprocess_framework.modules.process_module.configs.observability_audit import (
    ObservabilityAudit,
)


class _Sink:
    """Приёмник-список. Умеет отказывать — дубль, который всегда успешен, глушит гейт."""

    def __init__(self, *, ok: bool = True, raises: bool = False) -> None:
        self.documents: List[Dict[str, Any]] = []
        self._ok = ok
        self._raises = raises

    def __call__(self, document: Dict[str, Any]) -> Any:
        if self._raises:
            raise RuntimeError("БД недоступна")
        self.documents.append(document)
        return self._ok


class TestDocumentIsEmitted:
    def test_record_reaches_the_sink_with_kind_and_ts(self) -> None:
        sink = _Sink()
        audit = ObservabilityAudit(sink=sink, clock=lambda: 1234.5)

        audit.record("set", origin="command:config.reload", key="log_level", value="DEBUG")

        assert len(sink.documents) == 1
        doc = sink.documents[0]
        assert doc["kind"] == "audit"
        assert doc["ts"] == 1234.5
        assert doc["origin"] == "command:config.reload"
        assert doc["key"] == "log_level"
        assert doc["value"] == "DEBUG"

    def test_without_sink_nothing_changes(self) -> None:
        """Второе плечо: не подключённая плоскость — прежнее поведение, без падений."""
        audit = ObservabilityAudit(clock=lambda: 1.0)

        entry = audit.record("set", origin="watcher:app", key="log_level")

        assert entry["ok"] is True
        assert "document_failed" not in entry
        assert len(audit.ring) == 1

    def test_summary_names_the_action_and_key(self) -> None:
        sink = _Sink()
        audit = ObservabilityAudit(sink=sink, clock=lambda: 1.0)

        audit.record("expire", origin="ttl-sweeper", key="scopes.SYSTEM")

        assert sink.documents[0]["summary"] == "expire scopes.SYSTEM"


class TestSinkFailureDoesNotCancelTheChange:
    def test_refusing_sink_is_marked_not_swallowed(self) -> None:
        sink = _Sink(ok=False)
        audit = ObservabilityAudit(sink=sink, clock=lambda: 1.0)

        entry = audit.record("set", origin="command:config.reload", key="log_level")

        assert entry["document_failed"] is True, "отказ обязан быть виден в самой записи"
        assert len(audit.ring) == 1, "смена уже произошла — кольцо её держит"

    def test_raising_sink_does_not_escape_to_the_caller(self) -> None:
        sink = _Sink(raises=True)
        audit = ObservabilityAudit(sink=sink, clock=lambda: 1.0)

        entry = audit.record("set", origin="command:config.reload", key="log_level")

        assert entry["document_failed"] is True
        assert "БД недоступна" in entry["document_error"]
        assert len(audit.ring) == 1


class TestCollapsedRepeatDoesNotFloodThePlane:
    def test_repeat_emits_one_document_not_two(self) -> None:
        """Схлопывание уже защищает журнал — плоскость документов обязана получить то же.

        Подметальщик повторяет отказ каждый такт; сотня одинаковых документов в
        хранилище с долгим сроком — это тот же выеденный ресурс, только дороже.
        """
        sink = _Sink()
        audit = ObservabilityAudit(sink=sink, clock=lambda: 1.0)

        audit.record("expire", origin="ttl-sweeper", key="k", ok=False, error="занято")
        audit.record("expire", origin="ttl-sweeper", key="k", ok=False, error="занято")

        assert len(sink.documents) == 1
        assert audit.ring[-1]["repeats"] == 2


def _picklable_clock() -> float:
    """Часы функцией модуля, а не лямбдой.

    ``clock`` НЕ выбрасывается в ``__getstate__`` (в проде это ``time.time`` — функция
    модуля, пиклится). Лямбда здесь роняла бы пиклинг сама, и тест краснел бы не по
    проверяемой причине, а по устройству стенда.
    """
    return 1.0


def _picklable_log(message: str, is_error: bool = False) -> None:
    return None


class TestPicklingHazard:
    def test_layers_with_a_wired_sink_still_pickle(self) -> None:
        """Сток — замыкание на БД; он ОБЯЗАН выпадать из снимка, как и log.

        Стек слоёв пиклится на каждом boot/switch. Не выбрось `sink` в `__getstate__` —
        и пиклинг падает не здесь, а на старте процесса, где причина уже не видна.
        """
        audit = ObservabilityAudit(sink=_Sink(), log=_picklable_log, clock=_picklable_clock)
        audit.record("set", origin="switch", key="log_level")

        restored = pickle.loads(pickle.dumps(audit))  # nosec B301 — свой же объект, см. шапку

        assert restored.sink is None, "сток не должен переживать пиклинг"
        assert restored.log is None
        assert len(restored.ring) == 1, "а вот записи обязаны доехать"

    def test_restored_audit_keeps_working_without_a_sink(self) -> None:
        audit = ObservabilityAudit(sink=_Sink(), clock=_picklable_clock)

        restored = pickle.loads(pickle.dumps(audit))  # nosec B301 — свой же объект
        entry = restored.record("set", origin="switch", key="k")

        assert entry["ok"] is True
        assert "document_failed" not in entry
