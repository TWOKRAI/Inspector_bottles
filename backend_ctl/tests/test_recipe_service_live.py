"""Live-тест RED Task 1b.1: команды ``recipe.*`` на хабе (ADR-RCP-007, acceptance).

Сегодня ``RecipeService`` не существует (``NotImplementedError`` в скелете) и не
подключена к ``ProcessManager`` — эта команда бэкенду попросту неизвестна.
Тест бьёт по живому бэкенду через ``backend_ctl send_command`` (не через GUI),
как того требует acceptance Task 1b.1, и на СЕГОДНЯ фиксирует единственно
проверяемое: ответ НЕ ``success: True`` (unknown-command reply CommandManager'а,
форма не документирована отдельно — фиксируем полярность, не текст ошибки).

После GREEN этот же тест должен утверждать полный acceptance: ``recipe.list``
возвращает множество имён, совпадающее с ``ls recipes/*.yaml``; ``recipe.save``
с устаревшим ``base_rev`` — ``conflict`` без изменения файла на диске (sha256);
``recipe.activate`` меняет топологию, видимую в ``get_status``/``system_overview``,
и переживает рестарт (файл манифеста). Свой уникальный порт 8880-8899 — не
переиспользуем общую session-фикстуру (ловушка «двух бэкендов», см.
``backend_ctl/AGENTS.md``).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from backend_ctl.harness import BackendHarness

_PORT = 8887  # уникальный порт этого модуля (диапазон 8880-8899, DESIGN Task 1b.1)

# Стартовый рецепт временного манифеста: синтетический, без железа (как дефолт harness).
BOOT_RECIPE = "region_pipeline"


def write_temp_manifest(src_manifest: Path, tmp_root: Path) -> Path:
    """Копия ``app.yaml`` в ``tmp_root``: ``recipes``/``pipeline`` — относительно копии,
    прочие пути (system/base/styles) — абсолютные на репозиторий (их не копируем)."""
    raw = yaml.safe_load(src_manifest.read_text(encoding="utf-8"))
    repo_dir = src_manifest.parent
    raw["system"] = str(repo_dir / raw["system"])
    raw["base"] = [str(repo_dir / b) for b in raw.get("base") or []]
    if isinstance(raw.get("styles"), dict) and raw["styles"].get("dir"):
        raw["styles"]["dir"] = str(repo_dir / raw["styles"]["dir"])
    raw.pop("presentation", None)
    raw["recipes"] = "recipes"
    raw["pipeline"] = f"recipes/{BOOT_RECIPE}.yaml"
    out = tmp_root / "app.yaml"
    out.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def manifest_launcher(manifest: Path):
    """Headless-launcher из манифеста — та же дорога, что ``main`` (``SystemBuilder.from_manifest``)."""
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.main import build_launcher

    return build_launcher(load_manifest(manifest), None, include_presentation=False)


@pytest.fixture(scope="module")
def recipe_backend(tmp_path_factory: pytest.TempPathFactory):
    """Headless-бэкенд на своём порту + ИЗОЛИРОВАННАЯ временная копия recipes/app.yaml.

    Копия — по DESIGN ("temp copy of recipes/app.yaml, never the repo's real
    ones"): даже RED-запуск не должен зависеть от боевых файлов прототипа, а
    будущий GREEN-прогон (save/activate) обязан не мутировать репозиторий.
    Куда именно ``ProcessManager`` резолвит ``recipes_dir``/манифест на хабе —
    решение GREEN (Step 1 плана, "где хостить обработчики"); здесь временная
    копия готовится заранее, чтобы GREEN мог её переиспользовать без правки
    формы теста — открытый вопрос зафиксирован в отчёте тестировщика.
    """
    repo_root = Path(__file__).resolve().parents[2]
    src_recipes = repo_root / "multiprocess_prototype" / "recipes"
    src_manifest = repo_root / "multiprocess_prototype" / "app.yaml"

    tmp_root = tmp_path_factory.mktemp("recipe_live")
    tmp_recipes = tmp_root / "recipes"
    shutil.copytree(src_recipes, tmp_recipes)
    tmp_manifest = write_temp_manifest(src_manifest, tmp_root)

    # GREEN (Task 1b.1): бэкенд грузится из ВРЕМЕННОГО манифеста (launcher_factory,
    # Ф5.13) — хаб берёт recipes_dir и «активный» из него, recipe.activate пишет
    # pipeline во временный app.yaml, боевой не трогается.
    harness = BackendHarness(port=_PORT, launcher_factory=lambda: manifest_launcher(tmp_manifest))
    drv = harness.start()
    try:
        yield drv, tmp_recipes
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_list_get_conflict_activate_restart(recipe_backend) -> None:
    drv, tmp_recipes = recipe_backend

    expected_names = sorted(p.stem for p in tmp_recipes.glob("*.yaml"))
    assert expected_names, "фикстура прототипа должна содержать хотя бы один *.yaml рецепт"
    a_name = expected_names[0]

    # Утверждаем ПОЗИТИВНЫЙ acceptance (что обязано быть после GREEN), а не
    # "not success" — последнее тривиально верно для любой незнакомой команды
    # и не пинит контракт (vacuous RED). Сегодня хаб не знает recipe.*, поэтому
    # каждая проверка ниже падает по-настоящему — AssertionError с реальным
    # ответом, а не молчаливый green.

    # --- recipe.list: множество имён совпадает с ls recipes/*.yaml -----------
    list_res = drv.send_command("ProcessManager", "recipe.list", {}, timeout=8.0)
    assert list_res.get("success") is True, f"recipe.list не success: {list_res}"
    assert sorted(list_res.get("names") or []) == expected_names, list_res

    # --- recipe.get -> rev и тело ---------------------------------------------
    get_res = drv.send_command("ProcessManager", "recipe.get", {"name": a_name}, timeout=8.0)
    assert get_res.get("success") is True, f"recipe.get не success: {get_res}"
    assert isinstance(get_res.get("rev"), str) and get_res["rev"], get_res
    assert isinstance(get_res.get("body"), dict), get_res

    # --- recipe.save с заведомо устаревшим base_rev -> conflict, файл цел ----
    recipe_path = tmp_recipes / f"{a_name}.yaml"
    original_bytes = recipe_path.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()

    save_res = drv.send_command(
        "ProcessManager",
        "recipe.save",
        {"name": a_name, "base_rev": "stale-rev-does-not-exist", "body": {"whatever": True}},
        timeout=8.0,
    )
    assert save_res.get("success") is False, f"recipe.save с заведомо неверным base_rev должен отказать: {save_res}"
    assert save_res.get("error") == "conflict", save_res
    assert recipe_path.read_bytes() == original_bytes
    assert hashlib.sha256(recipe_path.read_bytes()).hexdigest() == original_sha

    # --- recipe.activate меняет топологию, видимую в get_status --------------
    activate_res = drv.send_command("ProcessManager", "recipe.activate", {"name": a_name}, timeout=8.0)
    assert activate_res.get("success") is True, f"recipe.activate не success: {activate_res}"
    assert isinstance(activate_res.get("apply"), dict), activate_res
