# -*- coding: utf-8 -*-
"""Ф4.5: редакция секретов — тесты АВТОРА на опасности механизма.

Опасности здесь не там, где кажется. «Маска вместо пароля» — простая часть,
и она ломается громко. Тихо ломаются три другие:

1. **Общий словарь.** После Ф4.1 ``to_dict()`` зовётся один раз, и один и тот
   же словарь едет ВСЕМ приёмникам, а его ``extra`` вдобавок держит ссылки на
   объекты вызывающего. Процессор, маскирующий на месте, испортил бы и запись
   всем сразу (включая tap оператора), и данные того, кто эту запись всего лишь
   залогировал.
2. **Fail-open по умолчанию.** Политика цепочки при броске процессора —
   доставить запись как есть. Для сэмплинга это правильно, для редакции это
   «сломались, поэтому показали секрет». Редактор ловит свои сбои сам.
3. **Ложное срабатывание.** Замаскированный ``token_count`` неотличим от
   работающей редакции ровно до момента, когда по нему пытаются разобрать
   инцидент.

Плюс проверка того, ради чего задача заводилась: секрет в **трейсбеке**,
который едет через ``ErrorManager.log_exception`` в текст сообщения и дальше в
``errors.log``. Тест идёт через настоящий менеджер и читает файл с диска —
fake-harness здесь доказывал бы только harness.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict

from multiprocess_framework.modules.error_module.configs.error_manager_config import (
    ErrorManagerConfig,
)
from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.redaction import (
    MASK,
    SECRET_FIELD_NAMES,
    SECRET_NAME_ROOTS,
    SecretRedactor,
    _message_may_carry_secret,
)


class _Tap:
    """Приёмник-соглядатай. Снимок ``extra`` — на момент ``write()``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        snapshot = dict(record)
        snapshot["extra"] = dict(record.get("extra") or {})
        with self._lock:
            self.records.append(snapshot)

    def close(self) -> None:
        pass


def _record(message: str = "нейтральный текст", **extra: Any) -> Dict[str, Any]:
    return {
        "timestamp": 0.0,
        "level": "INFO",
        "scope": "business",
        "message": message,
        "module": "probe",
        "extra": dict(extra),
        "seq": 1,
    }


class TestDoesNotTouchTheInput:
    """Главное свойство: вход не мутируется — ни словарь, ни вложенные в него."""

    def test_nested_dict_of_the_caller_survives_untouched(self) -> None:
        """Маскировка не правит вложенный словарь ВЫЗЫВАЮЩЕГО.

        Именно этот шов открылся в Ф4.1: ``extra`` едет в записи ссылкой на
        объект вызывающего. Поверхностная копия сверху плюс правка на месте
        внутри выглядит как «сделали копию» и портит чужие данные.
        """
        caller_owned = {"password": "hunter2", "host": "db-1"}
        record = _record(cfg=caller_owned, frame_id=7)

        redacted = SecretRedactor()("business", LogLevel.INFO, record)

        assert redacted is not record, "запись с находкой обязана быть НОВЫМ словарём"
        assert caller_owned == {"password": "hunter2", "host": "db-1"}, (
            f"словарь вызывающего мутирован редактором: {caller_owned}"
        )
        assert record["extra"]["cfg"] is caller_owned, "вход подменён на месте"
        assert redacted["extra"]["cfg"]["password"] == MASK
        assert redacted["extra"]["cfg"]["host"] == "db-1", "сосед по ветке не должен страдать"
        assert redacted["extra"]["frame_id"] == 7, "нетронутая ветка обязана доехать"

    def test_clean_record_travels_as_the_same_object(self) -> None:
        """Чистая запись — ноль аллокаций: возвращается ТОТ ЖЕ словарь.

        Контракт цепочки это разрешает, а записей без секретов — все, кроме
        считанных. Копия на каждой была бы ценой ради ничего.
        """
        redactor = SecretRedactor()
        record = _record("обычная запись", frame_id=7, worker="cam_0")

        assert redactor(LogScope.BUSINESS, LogLevel.INFO, record) is record
        assert redactor.records_redacted == 0


class TestMasking:
    """Что именно маскируется — и что НЕ маскируется."""

    def test_flat_and_nested_secret_keys(self) -> None:
        redacted = SecretRedactor()(
            "business",
            LogLevel.INFO,
            _record(api_key="ключ-стенда-1", nested={"deep": {"token": "abc"}}, fps=30),
        )
        assert redacted["extra"]["api_key"] == MASK
        assert redacted["extra"]["nested"]["deep"]["token"] == MASK
        assert redacted["extra"]["fps"] == 30

    def test_lookalike_field_names_are_left_alone(self) -> None:
        """``token_count`` — метрика, а не секрет.

        Подстрочный поиск съел бы её молча, и по замаскированной метрике потом
        разбирали бы инцидент.
        """
        redacted = SecretRedactor()(
            "business",
            LogLevel.INFO,
            _record("prompt tokenizer готов, token_count=512", token_count=512, tokenizer="bpe"),
        )
        assert redacted is not None
        assert redacted["extra"]["token_count"] == 512
        assert redacted["extra"]["tokenizer"] == "bpe"
        assert "512" in redacted["message"], f"метрика в тексте пострадала: {redacted['message']}"

    def test_message_forms_key_value_json_and_url(self) -> None:
        """Три формы в тексте: ``k=v``, ``"k": "v"`` и пароль внутри URL.

        Форма JSON — та самая, которую регулярка сперва обещала и не умела
        (закрывающая кавычка имени рвала совпадение); поймано прогоном.
        """
        redactor = SecretRedactor()
        out = redactor(
            "business",
            LogLevel.INFO,
            _record('сбой: password=hunter2, "api_key": "kv-1", dsn=postgres://u:pw@h/db'),
        )
        text = out["message"]
        assert "hunter2" not in text and "kv-1" not in text and "pw@" not in text, f"секрет уцелел в тексте: {text}"
        assert "password=***" in text
        assert '"api_key": "***"' in text, f"JSON-форма не замаскирована: {text}"
        assert "postgres://u:***@h/db" in text, f"пароль в URL уцелел: {text}"
        assert redactor.records_redacted == 1, "счётчик считает ЗАПИСИ, а не находки"


class TestPrefilterAgreesWithNames:
    """Дешёвый предфильтр обязан быть НАДмножеством точной регулярки."""

    def test_every_secret_name_is_covered_by_a_root(self) -> None:
        """Имя без корня стало бы невидимым для текста молча.

        Расхождение двух перечней — тот самый класс, что уже стоил проекту
        невидимой наружу метрики: в ``extra`` поле маскируется, в сообщении —
        нет, и заметить это можно только по утёкшему секрету.
        """
        uncovered = sorted(name for name in SECRET_FIELD_NAMES if not any(root in name for root in SECRET_NAME_ROOTS))
        assert not uncovered, (
            f"эти имена не покрыты ни одним корнем предфильтра: {uncovered}. "
            f"Добавь корень в SECRET_NAME_ROOTS И в развёрнутую цепочку "
            f"_message_may_carry_secret"
        )

    def test_unrolled_chain_matches_the_declared_roots(self) -> None:
        """Развёрнутая руками цепочка ``or`` не разъехалась с константой.

        Цепочка развёрнута ради 0.4 мкс на записи, и цена такой оптимизации —
        ровно этот риск: константу поправят, семь литералов забудут.
        """
        for root in SECRET_NAME_ROOTS:
            assert _message_may_carry_secret(f"строка с {root} внутри"), (
                f"корень {root!r} объявлен в SECRET_NAME_ROOTS, но цепочка в _message_may_carry_secret его не проверяет"
            )
        assert not _message_may_carry_secret("кадр обработан за 12.4 мс, очередь 3")

    def test_prefilter_hit_without_real_secret_does_not_count_as_redacted(self) -> None:
        """``keyboard`` проходит предфильтр — но записью с секретом не считается."""
        redactor = SecretRedactor()
        record = _record("keyboard подключена, authority сервиса ок")

        assert redactor("business", LogLevel.INFO, record) is record
        assert redactor.records_redacted == 0, "ложное срабатывание предфильтра засчитано как редакция"


class TestFailClosed:
    """Сбой редактора не имеет права показать неотредактированное."""

    def test_broken_extra_yields_marker_not_the_original(self) -> None:
        """``extra``, чей обход бросает, даёт маркер вместо содержимого.

        Общая политика цепочки здесь бы доставила запись как есть — то есть
        отдала бы оператору то, что редактор не смог проверить.
        """

        class _Hostile(dict):
            def items(self):  # noqa: D102 — намеренно враждебный объект
                raise RuntimeError("обход не удался")

        redactor = SecretRedactor()
        record = _record("текст с password=hunter2")
        record["extra"] = _Hostile()

        out = redactor("business", LogLevel.INFO, record)

        assert out is not None, "редактор не вправе поглощать запись"
        assert redactor.redaction_failures == 1
        assert "hunter2" not in out["message"], f"сбой редакции показал неотредактированный текст: {out['message']}"
        assert out["extra"] == {"redaction_failed": "RuntimeError"}

    def test_self_referencing_extra_does_not_fail(self) -> None:
        """Цикл в чужих данных не превращается в утечку.

        Без потолка глубины рекурсия дала бы ``RecursionError`` → сбой →
        (до fail-closed) запись уехала бы неотредактированной.
        """
        loop: Dict[str, Any] = {"password": "hunter2"}
        loop["self"] = loop
        redactor = SecretRedactor()

        out = redactor("business", LogLevel.INFO, _record(cfg=loop))

        assert redactor.redaction_failures == 0, "цикл уронил редактор"
        assert out["extra"]["cfg"]["password"] == MASK


class TestBothEmissionPaths:
    """Приёмка задачи: редакция работает на обоих путях, доказано артефактами."""

    def test_traceback_secret_is_masked_in_errors_log(self, tmp_path: Path) -> None:
        """Секрет из ТРЕЙСБЕКА не доезжает до ``errors.log``.

        Ради этого случая задача и заведена: ``log_exception`` склеивает
        ``traceback.format_exc()`` в текст, и это severity-путь ErrorManager —
        тот самый, который до Ф4.2 был отдельным override'ом.

        Оракул — файл на диске, а не наш же счётчик.
        """
        mgr = ErrorManager(
            manager_name="RedactionErrPath",
            config=ErrorManagerConfig(
                app_name="redaction",
                enable_batching=False,
                critical_file_path=str(tmp_path / "critical.log"),
                error_file_path=str(tmp_path / "errors.log"),
                warnings_file_path=None,
            ),
        )
        mgr.initialize()
        try:
            try:
                raise ValueError("не подключиться: dsn=postgres://user:hunter2@db/app token='abc123'")
            except ValueError as exc:
                mgr.log_exception(exc, message="сбой подключения", module="probe")
            mgr.flush()
            stats = mgr.get_stats()
        finally:
            mgr.shutdown()

        payload = (tmp_path / "errors.log").read_text(encoding="utf-8")
        assert "hunter2" not in payload, f"пароль из трейсбека лёг в errors.log:\n{payload}"
        assert "abc123" not in payload, f"токен из трейсбека лёг в errors.log:\n{payload}"
        assert MASK in payload, "маски в файле нет — редакция не отработала вовсе"
        assert stats["records_redacted"] >= 1, "счётчик редакции молчит на severity-пути"

    def test_tap_and_channel_see_the_same_masked_record(self, tmp_path: Path) -> None:
        """Оба приёмника видят ОДНО замаскированное — шов общего словаря.

        Tap уходит оператору и в backend_ctl, канал — на диск. Запись у них
        одна на всех, поэтому «замаскировано в файле, но не в tap'е» — не
        теория: ровно так выглядела бы редакция, поставленная после tap'ов.
        """
        mgr = LoggerManager(manager_name="RedactionSeam")
        mgr.initialize()
        tap = _Tap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)
        caller_owned = {"password": "hunter2", "host": "db-1"}
        try:
            mgr.business(LogLevel.INFO, "старт с password=hunter2", "probe", cfg=caller_owned)
            mgr.flush()
        finally:
            mgr.shutdown()

        seen = [r for r in tap.records if r["module"] == "probe"]
        assert len(seen) == 1, f"ожидалась одна запись, получено {len(seen)}"
        assert seen[0]["extra"]["cfg"]["password"] == MASK, "tap оператора увидел сырой секрет"
        assert "hunter2" not in seen[0]["message"], f"текст в tap'е не замаскирован: {seen[0]}"
        assert caller_owned == {"password": "hunter2", "host": "db-1"}, (
            "данные вызывающего испорчены редакцией по пути к приёмникам"
        )

    def test_redaction_is_on_without_anyone_registering_it(self) -> None:
        """Никто не звал ``add_processor`` — а редакция уже работает.

        Проводка после boot оставила бы окно загрузки без редакции; поэтому
        регистрация в конструкторе общего предка, и поэтому же тест проверяет
        менеджер, только что созданный, без единой настройки.
        """
        mgr = LoggerManager(manager_name="RedactionDefault")
        mgr.initialize()
        tap = _Tap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)
        try:
            mgr.business(LogLevel.INFO, "боевой конфиг", "probe", api_key="ключ-стенда-1")
            mgr.flush()
            stats = mgr.get_stats()
        finally:
            mgr.shutdown()

        seen = [r for r in tap.records if r["module"] == "probe"]
        assert seen and seen[0]["extra"]["api_key"] == MASK, f"редакция не включена по построению: {seen}"
        assert stats["records_redacted"] == 1
        assert stats["records_dropped_by_processor"] == 0, "редактор не вправе поглощать записи"
        assert stats["processor_failures"] == 0
