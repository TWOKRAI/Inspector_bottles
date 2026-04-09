# -*- coding: utf-8 -*-
"""Tests for RouterSchemaAdapter."""
import unittest
from typing import Any, Dict

from ..adapters.schema_adapter import RouterSchemaAdapter


class _FR:
    def __init__(self, channel: str, priority: int = 0):
        self.channel = channel
        self.priority = priority


class _Meta:
    def __init__(self, routing: Any = None, access_level: int = 0):
        self.routing = routing
        self.access_level = access_level


class _SchemaDictRouting:
    @classmethod
    def get_all_fields_meta(cls) -> Dict[str, Any]:
        return {
            "a": _Meta(routing={"channel": "ctrl", "priority": 2}),
            "b": _Meta(routing={"channel": "ctrl", "priority": 2}),
            "plain": _Meta(),
        }


class _SchemaObjectRouting:
    @classmethod
    def get_all_fields_meta(cls) -> Dict[str, Any]:
        return {
            "x": _Meta(routing=_FR("data", 1)),
        }


class _SchemaNoMeta:
    pass


class TestRouterSchemaAdapter(unittest.TestCase):

    def test_adapt_extracts_channels_from_field_routing(self):
        ad = RouterSchemaAdapter()
        routes = ad.adapt(_SchemaDictRouting)
        self.assertIn("ctrl", routes)
        self.assertEqual(set(routes["ctrl"]["fields"]), {"a", "b"})
        self.assertEqual(routes["ctrl"]["priority"], 2)

    def test_adapt_returns_empty_for_no_routing(self):
        ad = RouterSchemaAdapter()
        self.assertEqual(ad.adapt(_SchemaNoMeta), {})

    def test_adapt_object_field_routing(self):
        ad = RouterSchemaAdapter()
        routes = ad.adapt(_SchemaObjectRouting)
        self.assertIn("data", routes)
        self.assertEqual(routes["data"]["fields"], ["x"])

    def test_adapt_instance_includes_values_when_requested(self):
        ad = RouterSchemaAdapter()

        class Row:
            @classmethod
            def get_all_fields_meta(cls):
                return {"x": _Meta(routing=_FR("data", 1))}

            def model_dump(self):
                return {"x": 42}

        routes = ad.adapt_instance(Row(), include_values=True)
        self.assertIn("values", routes["data"])
        self.assertEqual(routes["data"]["values"], {"x": 42})

    def test_get_all_channels(self):
        ad = RouterSchemaAdapter()
        names = sorted(ad.get_all_channels(_SchemaDictRouting))
        self.assertEqual(names, ["ctrl"])

    def test_extract_channel_info_dict_format(self):
        ad = RouterSchemaAdapter()
        ch, pr = ad._extract_channel_info(_Meta(routing={"channel": "c", "priority": 5}))
        self.assertEqual(ch, "c")
        self.assertEqual(pr, 5)

    def test_extract_channel_info_object_format(self):
        ad = RouterSchemaAdapter()
        ch, pr = ad._extract_channel_info(_Meta(routing=_FR("z", 3)))
        self.assertEqual(ch, "z")
        self.assertEqual(pr, 3)

    def test_adapt_respects_min_access_level(self):
        class S:
            @classmethod
            def get_all_fields_meta(cls):
                return {
                    "low": _Meta(routing={"channel": "c"}, access_level=0),
                    "high": _Meta(routing={"channel": "c"}, access_level=5),
                }

        ad = RouterSchemaAdapter()
        routes = ad.adapt(S, min_access_level=5)
        self.assertEqual(routes["c"]["fields"], ["high"])

    def test_adapt_include_no_channel(self):
        class S:
            @classmethod
            def get_all_fields_meta(cls):
                return {"u": _Meta()}

        ad = RouterSchemaAdapter()
        routes = ad.adapt(S, include_no_channel=True)
        self.assertIn("__unrouted__", routes)
        self.assertIn("u", routes["__unrouted__"]["fields"])


if __name__ == "__main__":
    unittest.main()
