# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
# -*- coding: utf-8 -*-
"""C-30 repro: run each GUI recipe writer on a scratch copy of the pre-defect recipe."""

import shutil
import sys
import difflib
from pathlib import Path
import yaml

SP = Path(sys.argv[1])
before = SP / "before.yaml"
observed = SP / "observed.yaml"

from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
from multiprocess_prototype.domain.entities.recipe import Recipe


class _RM:  # stub RecipeManager: read_recipe == framework manager.read_recipe (yaml.safe_load)
    def __init__(self, d):
        self.d = d

    def read_recipe(self, slug):
        return yaml.safe_load((self.d / f"{slug}.yaml").read_text(encoding="utf-8"))

    def get_active(self):
        return "letter_robot_sim"


def run(name, fn):
    d = SP / name
    d.mkdir(exist_ok=True)
    shutil.copy(before, d / "letter_robot_sim.yaml")
    store = RecipeStoreFromManager(_RM(d), d)
    fn(store)
    out = (d / "letter_robot_sim.yaml").read_text(encoding="utf-8")
    ref = observed.read_text(encoding="utf-8")
    same = out == ref
    ndiff = sum(
        1
        for l in difflib.unified_diff(ref.splitlines(), out.splitlines(), lineterm="", n=0)
        if l[:1] in "+-" and not l.startswith(("+++", "---"))
    )
    print(f"[{name}] byte-identical to efc2612c3: {same}; differing lines vs efc2612c3: {ndiff}")
    for marker in (
        "gui_positions: {}",
        "restart_policy: {}",
        "extras: {}",
        "src_dtype:",
        "# T3.7",
        "    name: default",
        "  name: default",
    ):
        print(f"    count {marker!r}: {out.count(marker)}")


# A) Displays tab: DisplayCatalogFromRecipe.persist()/update()/register() -> RecipeStore.write(slug, Recipe)
def displays_path(store):
    from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import DisplayCatalogFromRecipe

    cat = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=lambda: "letter_robot_sim")
    cat.persist()


# B) Recipes tab Save / Pipeline Save / closeEvent: save_editor_topology_to_recipe -> save_raw
def recipes_save_path(store):
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe

    raw = store.read_raw("letter_robot_sim")
    topo = Recipe.from_dict(raw).blueprint.to_dict()  # same shape as TopologyRepository.load().to_dict()
    save_editor_topology_to_recipe(store, "letter_robot_sim", topo)


# C) Camera tab persist: read_raw -> mutate -> save_raw(whole raw)
def camera_path(store):
    raw = store.read_raw("letter_robot_sim")
    store.save_raw("letter_robot_sim", raw)


run("A_displays_persist", displays_path)
run("B_recipes_save", recipes_save_path)
run("C_camera_save_raw_whole", camera_path)
