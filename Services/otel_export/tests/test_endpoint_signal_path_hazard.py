# -*- coding: utf-8 -*-
"""Опасности адреса приёмника: путь сигнала обязателен, и он доезжает до провода.

**Откуда взялись эти тесты.** Живой прогон Task 2.3 против НАСТОЯЩЕГО приёмника
(`otelcol` 0.158.0) показал `exported=0` и `export_failed=28` при том, что вся Ф2
закрывалась зелёной. Замер вручную, три точки:

| POST | ответ |
|---|---|
| ``http://127.0.0.1:4318`` | **404** |
| ``http://127.0.0.1:4318/v1/logs`` | **200** |
| ``http://127.0.0.1:4318/v1/traces`` | 404 — контроль: дело в пути, не в теле |

Скрывала это заглушка стенда Task 2.2: она принимала POST по ЛЮБОМУ пути и
отвечала 200, поэтому `exported` рос и форма адреса выглядела рабочей. Ровно тот
случай, о котором правило проекта говорит «фейковая оснастка доказывает
оснастку»: 102 теста из 214 пинили форму, которая ни разу не доставила запись.

**Что здесь сторожится, по одному свойству на класс:**

1. поведение SDK, на котором стоит всё решение (путь дописывается ТОЛЬКО на
   env-дороге, явный аргумент уходит дословно) — пин на чужой контракт, чтобы
   обновление extras ломало тест, а не доставку;
2. отказ схемы на адресе без пути, и текст отказа называет лекарство;
3. адрес с путём доезжает до SDK БЕЗ изменений (наш код тоже ничего не дописывает);
4. фрагмент топологии, который мы поставляем, проходит схему сервиса — дыра, через
   которую дефект и приехал: yaml не проверял никто.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from Services.otel_export.config import OtelExportConfig

#: Фрагмент, который поставляется вместе с плагином (Task 3.1 включает им экспортёр).
TOPOLOGY_FRAGMENT = (
    Path(__file__).resolve().parents[3] / "multiprocess_prototype" / "backend" / "topology" / "otel_export.yaml"
)


class TestSdkUsesTheExplicitEndpointVerbatim:
    """Пин на чужой контракт: именно из него следует наш отказ.

    Если однажды SDK начнёт дописывать путь и к явному аргументу, красным станет
    ЭТОТ тест — и тогда валидатор ниже надо пересматривать, а не доставку чинить.
    """

    def test_explicit_endpoint_is_not_extended_with_a_signal_path(self):
        exporter_module = pytest.importorskip(
            "opentelemetry.exporter.otlp.proto.http._log_exporter",
            reason="extras [otel] не установлены — пин на SDK проверять не на чем",
        )

        bare = exporter_module.OTLPLogExporter(endpoint="http://collector.local:4318")
        with_path = exporter_module.OTLPLogExporter(endpoint="http://collector.local:4318/v1/logs")

        # Приватное имя — осознанно: публичного способа спросить SDK «куда ты
        # пошлёшь» нет, а свойство важнее опрятности. Смена имени в SDK обязана
        # ломать этот тест громко, а не тихо возвращать доставку в никуда.
        assert bare._endpoint == "http://collector.local:4318"
        assert with_path._endpoint == "http://collector.local:4318/v1/logs"


class TestEndpointWithoutSignalPathIsRefused:
    """Отказ на старте против тихо неверного адреса, который выглядит отказом сети."""

    @pytest.mark.parametrize(
        "bad",
        [
            "http://127.0.0.1:4318",
            "http://127.0.0.1:4318/",
            "https://collector.example.internal:4318",
        ],
    )
    def test_address_without_a_path_is_refused_and_the_message_names_the_cure(self, bad: str):
        with pytest.raises(ValidationError) as exc:
            OtelExportConfig(endpoint=bad)

        text = str(exc.value)
        assert "/v1/logs" in text, f"отказ не называет лекарство: {text!r}"
        assert "404" in text, f"отказ не называет наблюдаемое следствие: {text!r}"

    @pytest.mark.parametrize(
        "good",
        [
            "http://127.0.0.1:4318/v1/logs",
            "https://collector.example.internal:4318/v1/logs",
            "http://gateway.local/ingest/otlp/v1/logs",
        ],
    )
    def test_address_with_a_path_is_accepted_unchanged(self, good: str):
        """Пара к предыдущему: без неё «отвергает» неотличимо от «отвергает всё».

        И заодно второе свойство: принятое значение возвращается ДОСЛОВНО. Наш
        код не нормализует адрес — ни слэшем, ни регистром, — иначе оператор
        читал бы в readback не то, что уйдёт на провод.
        """
        assert OtelExportConfig(endpoint=good).endpoint == good


class TestShippedTopologyFragmentPassesTheServiceSchema:
    """Дыра, через которую дефект приехал: поставляемый yaml не проверял никто.

    Тест читает НАСТОЯЩИЙ файл, а не копию: копия разошлась бы с поставкой молча,
    и сторож охранял бы собственную фикстуру.
    """

    def _plugin_entry(self) -> dict:
        doc = yaml.safe_load(TOPOLOGY_FRAGMENT.read_text(encoding="utf-8"))
        for process in doc["processes"]:
            for plugin in process.get("plugins") or []:
                if plugin.get("plugin_name") == "otel_export":
                    return plugin
        raise AssertionError(f"в {TOPOLOGY_FRAGMENT} нет записи плагина otel_export")

    def test_fragment_exists_and_declares_the_exporter(self):
        entry = self._plugin_entry()
        assert entry["plugin_class"].endswith("OtelExportPlugin")

    def test_fragment_values_pass_the_service_schema(self):
        entry = self._plugin_entry()
        fields = {key: value for key, value in entry.items() if key in OtelExportConfig.model_fields}

        cfg = OtelExportConfig(**fields)

        # Литерал, а не производная от того же файла: значение, выведенное из
        # предмета проверки, согласилось бы с любым ответом, включая 404.
        assert cfg.endpoint == "http://127.0.0.1:4318/v1/logs"
