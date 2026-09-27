"""Тест лида Task 1.2a (ревью it.1, S4): пробел матрицы инъекций.

Инъекция L2 («commit пишет все ключи, а не только изменённые») не убила ни одного теста:
`update_yaml_preserving` сохраняет комментарий у самого ключа, даже если значение
перезаписано. Разница видна только на комментарии ВНУТРИ поддерева нетронутого ключа —
здесь `layers`, когда правится лишь `defect_probability`.
"""

from __future__ import annotations

import copy

from Plugins.sim.scene_source.tests.test_scene_source_hazards_1_2a import _cmd, _make_fixture, _new_plugin

_LAYERS_COMMENT = "  # внутри слоя диска — переживает правку соседнего ключа"


def test_commit_keeps_comment_inside_untouched_layers(tmp_path):
    preset_path = _make_fixture(tmp_path)
    text = preset_path.read_text(encoding="utf-8")
    # Комментарий в КОНЦЕ строки внутри элемента списка — он привязан к вложенному узлу, а не к
    # ключу `layers` (строка-комментарий перед `- name:` ruamel вешает на сам ключ и переживает
    # даже полную перезапись — первая версия теста из-за этого не ловила инъекцию L2).
    assert "sprite_source: disk.png" in text
    preset_path.write_text(
        text.replace("sprite_source: disk.png", "sprite_source: disk.png" + _LAYERS_COMMENT, 1), encoding="utf-8"
    )

    plugin, _sp = _new_plugin(preset_path)
    got = _cmd(plugin, "preset.get", {})
    new_preset = copy.deepcopy(got["preset"])
    new_preset["defect_probability"] = 0.5
    res = _cmd(plugin, "preset.commit", {"preset": new_preset, "base_rev": got["rev"]})

    assert res["status"] == "ok" and res["changed"] is True, res
    after = preset_path.read_text(encoding="utf-8")
    assert _LAYERS_COMMENT.strip() in after, after
    assert "defect_probability: 0.5" in after, after
