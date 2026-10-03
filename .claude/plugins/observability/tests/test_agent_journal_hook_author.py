"""Тесты автора хука agent-journal.sh: то, что видно только изнутри механизма.

Тесты тестера (test_agent_journal_hook.py) писались слепо, по приёмке. Здесь — места,
где хук ломается из-за того, КАК он устроен: хук запускает git подпроцессом, и вывод git
декодируется кодировкой процесса, а не UTF-8 (на этой машине cp1251).
"""

from __future__ import annotations

from test_agent_journal_hook import (  # noqa: F401  (фикстуры и хелперы тестера)
    _git,
    jdir,
    make_repo,
    read_records,
    repos,
    run_hook,
    start_payload,
)


def test_cyrillic_branch_name_is_recorded_as_is(jdir, tmp_path):
    """Ветка с кириллицей: без явной UTF-8 вывод git читался как cp1251 и давал кракозябры."""
    repo = make_repo(tmp_path, "repo_ru", "имя_ветки")
    assert _git(repo, "branch", "--show-current").returncode == 0
    assert run_hook(jdir, start_payload(repo), repo).returncode == 0
    assert read_records(jdir)[0]["branch"] == "имя_ветки"


def test_session_start_records_source(jdir, repos):
    """source отличает новую сессию от компакции и resume: SessionStart приходит на все четыре."""
    x, _ = repos
    payload = {"hook_event_name": "SessionStart", "session_id": "sess-7", "cwd": str(x), "source": "compact"}
    assert run_hook(jdir, payload, x).returncode == 0
    assert read_records(jdir)[0]["source"] == "compact"


def test_source_is_empty_when_the_event_has_none(jdir, repos):
    x, _ = repos
    assert run_hook(jdir, start_payload(x), x).returncode == 0
    assert read_records(jdir)[0]["source"] == ""
