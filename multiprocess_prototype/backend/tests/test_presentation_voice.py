"""Тесты «голоса» презентационного overlay процесса ``gui`` (S-22, plans/QUEUE.md).

Пишутся ДО правки ``multiprocess_prototype/backend/launch.py`` — по контракту из ТЗ
задачи S-22, без чтения самого ``launch.py`` и ``frontend/presentation.yaml``.

Дефект, который эти тесты обязаны поймать: когда overlay НЕ накладывается на
процесс ``gui`` (headless-воплощение остаётся как объявлено рецептом), система
молчит об этом. Снаружи бут выглядит штатно — процессы живые, команды отвечают,
Гц идут, — но окна нет и не будет. Это стоило проекту 174 бутов без окна против
6 с окном, ни один не был назван вслух.

ПРАВКА АВТОРА ПОСЛЕ НЕЗАВИСИМОГО ТЕСТЕРА (2026-08-18, S-22). Тестер выбрал
содержательным маркером причины К2 голое слово ``headless`` и потребовал, чтобы в
тексте К1 его НЕ было. Этот контракт противоречит самому К1: К1 обязан назвать
фактический класс процесса, а он называется
``…headless_process.HeadlessGuiProcess`` — слово ``headless`` в тексте К1 есть
неизбежно. Прав К1 (он в критериях приёмки дословно), маркер заменён на имя
переменной окружения ``INSPECTOR_HEADLESS``: она называет именно ПРИЧИНУ
(требование вызывающего), а не воплощение процесса, и в тексте К1 ей взяться
неоткуда. Модель тестера здесь была неверной — записано, а не замолчано.

Там же снят ``builder.blueprint``: публичного атрибута у ``SystemBuilder`` нет
(есть приватный ``_blueprint``), и заводить его РАДИ ТЕСТА значило бы растить
публичный API под проверку. Прекондиция К4 берётся из самих yaml-файлов рецепта
и фундамента — она вообще не зависит от кода под тестом, что честнее.

Публичный контракт (дан в ТЗ, НЕ выведен из кода):

    builder = SystemBuilder.from_manifest(app, pipeline_override=None, *, include_presentation=True)


Используются РЕАЛЬНЫЕ файлы прототипа (разрешено к чтению по заданию):
  - ``multiprocess_prototype/app.yaml`` — тот же манифест, что грузит существующий
    ``test_build_characterization.py`` (``load_manifest`` + ``SystemBuilder.from_manifest``
    там уже применяются к боевому app.yaml — конвенция подтверждена соседним тестом).
  - рецепт ``color_inspect`` — объявляет ``gui`` в headless-воплощении
    (``multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess``,
    см. ``recipes/color_inspect.yaml``).
  - рецепт ``g1_perf_probe`` — вообще не объявляет ``gui`` (2 процесса:
    synthetic_source → consumer, см. ``recipes/g1_perf_probe.yaml``).
  - ``frontend/presentation.yaml`` — реальный overlay-файл; его СОДЕРЖИМОЕ здесь
    не читается (запрещено заданием), используется только его путь — открывает
    и парсит его код под тестом, а не тест.

Ни один вызов ``SystemBuilder.from_manifest`` не имеет права повесить прогон —
каждый идёт в daemon-поток с join-дедлайном (``_call_from_manifest``).
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

import pytest

from multiprocess_prototype.backend.config.manifest import load_manifest
from multiprocess_prototype.backend.launch import SystemBuilder

# backend/tests/<file> → parents[3] == корень репозитория (тот же расчёт, что
# в соседнем test_build_characterization.py).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_YAML = PROJECT_ROOT / "multiprocess_prototype" / "app.yaml"
PRESENTATION_YAML = PROJECT_ROOT / "multiprocess_prototype" / "frontend" / "presentation.yaml"

# Рецепт с gui в headless-воплощении (recipes/color_inspect.yaml, process_class =
# multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess).
RECIPE_WITH_GUI = "color_inspect"

# Рецепт БЕЗ процесса gui вообще (recipes/g1_perf_probe.yaml: synthetic_source → consumer).
RECIPE_WITHOUT_GUI = "g1_perf_probe"

# --- Литералы контракта из ТЗ S-22 — НЕ выводятся из реализации под тестом ---
HEADLESS_GUI_CLASS = "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess"
QT_GUI_CLASS = "multiprocess_prototype.frontend.process.GuiProcess"
RUN_ENTRY_POINT = "multiprocess_prototype/frontend/run.py"
# Маркер ПРИЧИНЫ К2 — имя env-ручки, а не слово «headless» (см. правку выше).
HEADLESS_FLAG_MARKER = "INSPECTOR_HEADLESS"


@pytest.fixture
def app(monkeypatch):
    """Загруженный боевой манифест без env-оверлея presentation.

    ``app.yaml`` сегодня не задаёт ``presentation:`` явно — precondition ниже
    это фиксирует, чтобы дрейф app.yaml не тихо перекосил К1/К5 (они рассчитывают
    именно на "presentation не задан по умолчанию").
    """
    monkeypatch.delenv("INSPECTOR_PRESENTATION", raising=False)
    loaded = load_manifest(APP_YAML)
    assert loaded.presentation is None, (
        "прекондиция теста нарушена: app.yaml (или env INSPECTOR_PRESENTATION) "
        "теперь сам задаёт presentation — К1/К5 рассчитывают на 'не задан по умолчанию', "
        "нужно поправить фикстуру"
    )
    return loaded


def _call_from_manifest(app_manifest, *, pipeline_override, include_presentation, timeout=15.0):
    """``SystemBuilder.from_manifest`` в daemon-потоке с join-дедлайном.

    Защита от зависания: если вызов не вернётся за ``timeout`` секунд — тест
    падает явно (``pytest.fail``), а не виснет вместе с прогоном.
    """
    result: "queue.Queue" = queue.Queue()

    def _run() -> None:
        try:
            builder = SystemBuilder.from_manifest(
                app_manifest,
                pipeline_override=pipeline_override,
                include_presentation=include_presentation,
            )
            result.put(("ok", builder))
        except BaseException as exc:  # noqa: BLE001 — протащить исключение через границу потока
            result.put(("error", exc))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        pytest.fail(f"SystemBuilder.from_manifest завис (> {timeout}с) — тест не должен виснуть")

    status, payload = result.get_nowait()
    if status == "error":
        raise payload
    return payload


# --- К1 ----------------------------------------------------------------------


def test_k1_no_presentation_names_actual_class_and_run_entry(app, capsys):
    """К1: ``app.presentation is None`` → stderr называет ФАКТИЧЕСКИЙ класс gui
    в этой сборке И упоминает вход, дающий окно (``frontend/run.py``)."""
    _call_from_manifest(app, pipeline_override=RECIPE_WITH_GUI, include_presentation=True)
    captured = capsys.readouterr()

    assert HEADLESS_GUI_CLASS in captured.err, (
        "К1: голос обязан назвать фактический класс, который получит gui в этой "
        f"сборке ({HEADLESS_GUI_CLASS}) — его нет в stderr:\n{captured.err!r}"
    )
    assert RUN_ENTRY_POINT in captured.err, (
        f"К1: голос обязан упомянуть вход, дающий окно ({RUN_ENTRY_POINT}) — его нет в stderr:\n{captured.err!r}"
    )


# --- К2 ----------------------------------------------------------------------


def test_k2_headless_override_names_headless_flag_as_cause(app, capsys):
    """К2: presentation задан, но include_presentation=False → причина в stderr —
    именно headless-флаг вызывающего."""
    app_with_presentation = app.model_copy(update={"presentation": PRESENTATION_YAML})

    _call_from_manifest(app_with_presentation, pipeline_override=RECIPE_WITH_GUI, include_presentation=False)
    captured = capsys.readouterr()

    assert HEADLESS_FLAG_MARKER in captured.err, (
        "К2: сообщение обязано называть причиной именно headless-флаг вызывающего "
        f"(маркер {HEADLESS_FLAG_MARKER} отсутствует) — stderr:\n{captured.err!r}"
    )


def test_k1_and_k2_texts_differ_in_substance(app, capsys):
    """К1 и К2 — ДВА РАЗНЫХ факта («overlay не задан» vs «overlay задан, но
    перебит headless-флагом»). Слипание в один текст — дефект, сформулировано
    явно в ТЗ как ключевой критерий."""
    _call_from_manifest(app, pipeline_override=RECIPE_WITH_GUI, include_presentation=True)
    text_k1 = capsys.readouterr().err

    app_with_presentation = app.model_copy(update={"presentation": PRESENTATION_YAML})
    _call_from_manifest(app_with_presentation, pipeline_override=RECIPE_WITH_GUI, include_presentation=False)
    text_k2 = capsys.readouterr().err

    assert text_k1.strip() and text_k2.strip(), (
        f"оба повода обязаны хоть что-то напечатать в stderr — К1={text_k1!r}, К2={text_k2!r}"
    )
    assert text_k1 != text_k2, (
        "К1 и К2 напечатали ОДИНАКОВЫЙ текст — 'overlay не задан вовсе' и "
        "'overlay задан, но перебит headless-флагом' обязаны различаться по "
        f"существу:\nК1: {text_k1!r}\nК2: {text_k2!r}"
    )
    # Различие обязано быть содержательным (не пунктуацией): маркер headless-причины
    # обязан быть ТОЛЬКО в К2, иначе тест 'text_k1 != text_k2' проходит на разнице
    # в один пробел и ничего не доказывает.
    assert HEADLESS_FLAG_MARKER in text_k2 and HEADLESS_FLAG_MARKER not in text_k1, (
        f"содержательный маркер причины ({HEADLESS_FLAG_MARKER}) обязан присутствовать "
        f"ТОЛЬКО в К2:\nК1: {text_k1!r}\nК2: {text_k2!r}"
    )


# --- К3 ----------------------------------------------------------------------


def test_k3_overlay_applied_prints_neither_k1_nor_k2_voice(app, capsys):
    """К3: overlay реально наложен (presentation задан И include_presentation=True)
    → ни голос К1, ни голос К2 в stderr не звучит."""
    app_with_presentation = app.model_copy(update={"presentation": PRESENTATION_YAML})

    _call_from_manifest(app_with_presentation, pipeline_override=RECIPE_WITH_GUI, include_presentation=True)
    captured = capsys.readouterr()

    assert RUN_ENTRY_POINT not in captured.err, (
        f"К3: overlay наложен, а голос К1 (про отсутствие presentation) всё равно прозвучал — stderr:\n{captured.err!r}"
    )
    assert HEADLESS_FLAG_MARKER not in captured.err, (
        f"К3: overlay наложен, а голос К2 (про headless-перебивку) всё равно прозвучал — stderr:\n{captured.err!r}"
    )


# --- К4 ----------------------------------------------------------------------


def test_k4_voice_silent_about_class_when_gui_absent_from_topology(app, capsys):
    """К4: если процесса gui нет в слитой топологии вовсе, голос не имеет права
    утверждать, каким классом gui поедет (ни headless-, ни Qt-именем)."""
    # Прекондиция берётся из самих yaml, а не из кода под тестом: слитая
    # топология = фундамент ⊕ рецепт, и ни один из двух файлов не объявляет gui.
    for source in (
        PROJECT_ROOT / "multiprocess_prototype" / "backend" / "topology" / "base.yaml",
        PROJECT_ROOT / "multiprocess_prototype" / "recipes" / f"{RECIPE_WITHOUT_GUI}.yaml",
    ):
        assert "process_name: gui" not in source.read_text(encoding="utf-8"), (
            f"прекондиция теста нарушена: {source.name} объявил процесс gui — "
            "для К4 нужна топология БЕЗ gui, выбери другой рецепт"
        )

    _call_from_manifest(app, pipeline_override=RECIPE_WITHOUT_GUI, include_presentation=True)

    captured = capsys.readouterr()
    assert HEADLESS_GUI_CLASS not in captured.err, (
        f"К4: gui в топологии нет, а голос всё равно назвал headless-класс — stderr:\n{captured.err!r}"
    )
    assert QT_GUI_CLASS not in captured.err, (
        f"К4: gui в топологии нет, а голос всё равно назвал Qt-класс — stderr:\n{captured.err!r}"
    )


# --- К5 ----------------------------------------------------------------------


def test_k5_voice_sounds_exactly_once_per_build(app, capsys):
    """К5: голос звучит РОВНО один раз за сборку — не на процесс, не в цикле."""
    _call_from_manifest(app, pipeline_override=RECIPE_WITH_GUI, include_presentation=True)
    captured = capsys.readouterr()

    occurrences = captured.err.count(RUN_ENTRY_POINT)
    assert occurrences == 1, (
        f"К5: маркер голоса встретился в stderr {occurrences} раз(а), ожидался "
        f"ровно 1 (не на процесс сборки, не в цикле) — stderr:\n{captured.err!r}"
    )


# --- Добор по находкам синхронного ревью 2026-08-18 ------------------------------
#
# Ревью нашло, что заявленное словом «ФАКТИЧЕСКИЙ» свойство не сторожил ни один
# тест и ни одна инъекция: все шесть тестов ездили по рецептам, где класс И ТАК
# headless, поэтому жёстко зашитая строка HeadlessGuiProcess в хвосте давала
# 6 passed. Плюс два достижимых состояния, где текст говорил неправду.

#: Топология, объявляющая gui Qt-классом САМА — без всякого overlay.
TOPOLOGY_WITH_QT_GUI = "multiprocess_prototype/backend/topology/archive/gui.yaml"

#: Общий префикс обоих голосов — по нему считается «ровно один раз» в ЛЮБОЙ ветке.
VOICE_PREFIX = "[launch] presentation:"


def test_k6_class_is_read_from_this_build_not_hardcoded(app, capsys):
    """Класс берётся ИЗ ЭТОЙ сборки, и исход выводится из него, а не из повода.

    Прежняя редакция печатала «окна не будет» константой: на топологии, которая
    объявила gui Qt-классом сама, голос уверенно врал. Тест держит оба конца —
    и что класс прочитан, и что вывод из него сделан верный.
    """
    _call_from_manifest(app, pipeline_override=TOPOLOGY_WITH_QT_GUI, include_presentation=True)
    err = capsys.readouterr().err

    assert QT_GUI_CLASS in err, (
        f"голос обязан назвать класс ИЗ ЭТОЙ сборки ({QT_GUI_CLASS}); если в тексте "
        f"стоит {HEADLESS_GUI_CLASS}, значит класс зашит, а не прочитан:\n{err!r}"
    )
    assert HEADLESS_GUI_CLASS not in err, f"назван чужой класс:\n{err!r}"
    assert "окна не будет" not in err, (
        f"топология объявила gui Qt-классом сама — окно будет, и голос не имеет права утверждать обратное:\n{err!r}"
    )
    assert RUN_ENTRY_POINT not in err, f"совет про вход бесполезен, когда окно и так будет:\n{err!r}"


def test_k7_qt_class_constant_matches_presentation_overlay():
    """Константа Qt-класса сверяется с ``presentation.yaml``, а не верится на слово.

    Голос отличает «окна не будет» от «окно всё-таки будет» сравнением с этой
    константой. Разъедься она с overlay'ем — голос начал бы врать тихо, и ни один
    прогон бы этого не заметил.
    """
    import yaml

    from multiprocess_prototype.backend.launch import PRESENTATION_PROCESS_CLASS

    overlay = yaml.safe_load(PRESENTATION_YAML.read_text(encoding="utf-8"))
    patched = {proc.get("process_name"): proc.get("process_class") for proc in overlay.get("processes") or []}
    assert patched.get("gui") == PRESENTATION_PROCESS_CLASS, (
        "PRESENTATION_PROCESS_CLASS разъехался с frontend/presentation.yaml: "
        f"константа={PRESENTATION_PROCESS_CLASS!r}, overlay={patched.get('gui')!r}"
    )


def test_k8_headless_branch_also_sounds_exactly_once(app, capsys):
    """К5 для ВТОРОЙ ветки: прежний счёт шёл по пути входа, которого в тексте
    headless-повода нет вовсе — ветку можно было заставить печатать дважды, и
    сьют оставался зелёным (находка ревью). Счёт — по общему префиксу."""
    app_with_presentation = app.model_copy(update={"presentation": PRESENTATION_YAML})
    _call_from_manifest(app_with_presentation, pipeline_override=RECIPE_WITH_GUI, include_presentation=False)
    err = capsys.readouterr().err

    assert err.count(VOICE_PREFIX) == 1, (
        f"голос headless-повода прозвучал {err.count(VOICE_PREFIX)} раз(а), ожидался ровно 1:\n{err!r}"
    )


def test_k9_third_reason_has_its_own_text(app, capsys):
    """Третий повод — overlay не задан И выставлен headless-флаг — свой текст.

    Отрицание «overlay задан И презентация разрешена» даёт три состояния, не два.
    Прежняя редакция складывала третье в первое и советовала оператору вход,
    который при живом ``INSPECTOR_HEADLESS`` окна всё равно не даст.
    """
    _call_from_manifest(app, pipeline_override=RECIPE_WITH_GUI, include_presentation=True)
    text_no_overlay = capsys.readouterr().err

    _call_from_manifest(app, pipeline_override=RECIPE_WITH_GUI, include_presentation=False)
    text_both = capsys.readouterr().err

    assert text_both.strip(), "третий повод обязан звучать"
    assert text_both != text_no_overlay, (
        "«overlay не задан» и «overlay не задан И флаг» слиплись в один текст:"
        f"\nбез флага: {text_no_overlay!r}\nс флагом:  {text_both!r}"
    )
    assert HEADLESS_FLAG_MARKER in text_both, (
        f"третий повод обязан назвать флаг ({HEADLESS_FLAG_MARKER}):\n{text_both!r}"
    )
    assert RUN_ENTRY_POINT in text_both, f"третий повод обязан назвать и вход — одного шага не хватит:\n{text_both!r}"


def test_k10_no_entry_advice_when_gui_absent(app, capsys):
    """Совет печатается, только если сработает: процесса gui нет — вход не поможет."""
    _call_from_manifest(app, pipeline_override=RECIPE_WITHOUT_GUI, include_presentation=True)
    err = capsys.readouterr().err

    assert err.strip(), "голос обязан звучать и здесь — просто без совета"
    assert RUN_ENTRY_POINT not in err, (
        "совет про вход бесполезен, когда gui в топологии нет вовсе: оператор потратит "
        f"бут, чтобы узнать то, что первая строка уже знает:\n{err!r}"
    )


#: Третий класс — ни headless-, ни Qt-шный. Нужен, чтобы отличить «класс прочитан»
#: от «класс совпал случайно»: на боевых рецептах он и так headless, а на
#: archive/gui.yaml — Qt-шный, поэтому зашитая константа в ветке «окна не будет»
#: оставалась зелёной под инъекцией (И7b). Найдено собственной инъекцией, не тестом.
THIRD_PARTY_GUI_CLASS = "multiprocess_prototype.generic_process_app.GenericProcessApp"


def test_k11_third_class_is_named_verbatim(app, capsys, tmp_path):
    """Класс печатается ДОСЛОВНО из топологии — не выбирается из двух известных."""
    topology = tmp_path / "gui_third_class.yaml"
    topology.write_text(
        "name: gui_third_class\n"
        "description: gui с классом, которого голос не знает\n"
        "processes:\n"
        "  - process_name: gui\n"
        f"    process_class: {THIRD_PARTY_GUI_CLASS}\n"
        "    plugins: []\n"
        "wires: []\n",
        encoding="utf-8",
    )

    _call_from_manifest(app, pipeline_override=str(topology), include_presentation=True)
    err = capsys.readouterr().err

    assert THIRD_PARTY_GUI_CLASS in err, f"голос обязан назвать класс дословно ({THIRD_PARTY_GUI_CLASS}):\n{err!r}"
    assert HEADLESS_GUI_CLASS not in err, f"назван зашитый headless-класс вместо прочитанного:\n{err!r}"
    assert "окна не будет" in err, f"класс не презентационный — окна не будет, и это надо сказать:\n{err!r}"
