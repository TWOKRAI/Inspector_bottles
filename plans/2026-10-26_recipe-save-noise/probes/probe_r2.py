# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
import sys
import yaml
import dataclasses
import tempfile
import shutil
from pathlib import Path
from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import DisplayCatalogFromRecipe
from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
from multiprocess_prototype.domain.entities.recipe import Recipe

d = Path(tempfile.mkdtemp(prefix="r2_", dir=sys.argv[2]))
shutil.copy(sys.argv[1], d / "letter_robot_sim.yaml")


class RM:
    def read_recipe(self, s):
        return yaml.safe_load((d / f"{s}.yaml").read_text(encoding="utf-8"))


class Cap(RecipeStoreFromManager):
    captured = None

    def write(self, slug, recipe):
        Cap.captured = recipe


store = Cap(RM(), d)
cat = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=lambda: "letter_robot_sim")
raw = store.read_raw("letter_robot_sim")
base = Recipe.from_dict(raw)
spec = cat.resolve("phone")
spec2 = (
    dataclasses.replace(spec, enabled=True)
    if dataclasses.is_dataclass(spec)
    else spec.model_copy(update={"enabled": True})
)
cat.update(spec2)
a, b = base.to_dict(), Cap.captured.to_dict()


def diff(x, y, p=""):
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            if k not in x or k not in y or x[k] != y[k]:
                diff(x.get(k), y.get(k), p + "/" + k)
    elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        for i, (u, v) in enumerate(zip(x, y)):
            if u != v:
                diff(u, v, f"{p}[{i}]")
    else:
        print("  ", p, repr(x), "->", repr(y))


print("update(phone, enabled=True): normalized delta paths:")
diff(a, b)
# no-edit: update with same spec
Cap.captured = None
cat.update(spec)
print("update(same spec) delta:", end=" ")
diff(a, Cap.captured.to_dict())
print("(end)")
