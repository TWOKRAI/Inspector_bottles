# -*- coding: utf-8 -*-
"""Корневой conftest: страж модальных окон в прогоне.

**Зачем.** Тест, который открыл модальное окно, не падает — он *ждёт клика*.
Прогон встаёт на неопределённое время, и на CI это выглядит как таймаут без
причины, а на машине владельца — как «тесты почему-то требуют нажать ОК». По
закону проекта тест, который висит вместо того чтобы упасть, хуже отсутствующего:
он прячет регрессию за ожиданием.

**Что делает.** Любой блокирующий вызов Qt-диалога в тесте становится
НАЗВАННЫМ падением: видно имя теста и имя вызова. Тесты, которым диалог нужен по
сути (проверка «Отмена не закрывает окно»), подменяют его сами — их подмена
ставится ПОСЛЕ этой и выигрывает.

**Почему BaseException, а не Exception.** Прод-код здесь щедр на
``except Exception`` вокруг GUI-вызовов (и правильно: отсутствие app не должно
ронять конструктор). Страж, пойманный такой веткой, снова превратился бы в
тишину — только теперь с зелёным тестом вместо честного ожидания.

Найдено 2026-08-10: три теста открывали модалку и ждали руки оператора —
``test_restart_no_proxy_does_not_clear`` (pre-flight «нет proxy») и два теста
индикатора dirty, у которых окно уходило в teardown с несохранёнными правками.
Страж показан красным на них до правки; проверка того, что он умеет краснеть, —
``multiprocess_prototype/frontend/tests/test_no_blocking_modals_guard.py``.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# matplotlib в тестовом процессе — только Agg (страховка класса, 2026-08-12)
# ---------------------------------------------------------------------------
# Сегодня для гейта строка ИНЕРТНА, и это проверено пробой, а не предположено:
# за полный прогон matplotlib не импортируется ни разу (session-end проба
# 2026-08-12: `mpl_imported=False`; досье и разбор ложной первой атрибуции —
# docs/sessions/2026-08-12_access_violation.md). Оставлена страховкой класса:
# при установленном PySide6 matplotlib резолвит backend в `qtagg` (факт:
# `python -c "import matplotlib; print(matplotlib.get_backend())"` → qtagg) —
# первый же будущий импортёр (ultralytics-плоттинг, отчёт с графиком) молча
# притащил бы в тестовый процесс второй источник QApplication и Qt-объекты вне
# qtbot-дисциплины. Интерактивный backend прогону не нужен нигде.
#
# Env, а не matplotlib.use(): сработать обязано ДО первого транзитивного
# импорта, а conftest корня исполняется раньше любого тестового модуля.
# setdefault, а не присваивание: оператор, сознательно выставивший свой
# backend, сильнее умолчания.
os.environ.setdefault("MPLBACKEND", "Agg")


class BlockingModalInTest(BaseException):
    """Тест открыл модальное окно и ждал бы клика оператора."""


#: Блокирующие вызовы Qt по классам. Не-блокирующие (``show``/``open``) НЕ
#: перехватываются: они прогон не останавливают, а значит не наш класс дефекта.
_BLOCKING_CALLS = {
    "QDialog": ("exec", "exec_"),
    "QMessageBox": ("exec", "exec_", "warning", "critical", "information", "question", "about"),
    "QFileDialog": ("getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"),
    "QInputDialog": ("getText", "getItem", "getInt", "getDouble"),
    "QColorDialog": ("getColor",),
    "QFontDialog": ("getFont",),
}


def _refuse(name: str):
    def _raise(*_args, **_kwargs):
        raise BlockingModalInTest(
            f"{name} открыт в тесте — прогон встал бы до клика оператора. "
            "Подмените диалог в самом тесте (monkeypatch), если проверяете его поведение."
        )

    return _raise


# ---------------------------------------------------------------------------
# Политика памяти GUI (T1): сборкой gc владеет главный поток, граница каждого теста
# ---------------------------------------------------------------------------
# Те же имена и тела — в корневом conftest.py и в multiprocess_framework/modules/conftest.py
# (в modules/ эти перекрывают корневые; из modules/ корень не грузится). Спека —
# plans/2026-10-03_lifecycle-owner-scope/task-T1.md, «Точки включения» 2–3.


@pytest.fixture(scope="session", autouse=True)
def _gui_memory_policy(pytestconfig: pytest.Config):
    """Сессия: автосборка выключена, сборка — тиком QTimer и на границах тестов."""
    from multiprocess_framework.modules.frontend_module.core.qt_gc_policy import (
        gui_memory_policy,
        install_gui_memory_policy,
    )

    pre = gui_memory_policy()
    policy = pre or install_gui_memory_policy(None, freeze=True, freeze_after_s=0.0, observe=True)
    yield policy
    pytestconfig.gc_policy_stats = policy.stats()
    if pre is None:
        policy.uninstall()


@pytest.fixture(autouse=True)
def _gui_memory_boundary(_gui_memory_policy):
    """Граница теста: автосборку не оставили включённой; мусор теста собран на главном потоке.

    Определена ПЕРВОЙ из function-autouse: её teardown идёт последним.
    """
    yield
    policy = _gui_memory_policy
    violated = policy.enforce()
    policy.collect_now()
    if violated:
        pytest.fail("Тест оставил автосборку gc включённой: восстановите прежнее состояние через paused_gc()")


@pytest.fixture(autouse=True)
def no_blocking_modals(monkeypatch):
    """Модалка в тесте — падение с именем вызова, а не ожидание клика."""
    try:
        from PySide6 import QtWidgets
    except ImportError:  # прогон без PySide6 — стеречь нечего
        yield
        return

    for cls_name, attrs in _BLOCKING_CALLS.items():
        cls = getattr(QtWidgets, cls_name, None)
        if cls is None:
            continue
        for attr in attrs:
            if hasattr(cls, attr):
                monkeypatch.setattr(cls, attr, staticmethod(_refuse(f"{cls_name}.{attr}")), raising=False)
    yield
