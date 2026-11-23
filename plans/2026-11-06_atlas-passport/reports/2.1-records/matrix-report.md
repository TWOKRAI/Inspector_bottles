# matrix-report: инъекции A1 (Task 2.1, stage 3)

База: 24 passed, 0 failed, RC 0, дерево чистое (ветка feat/atlas-passport, c651cea97).
Команда: machine_gate.sh light atlas-matrix, pytest test_scan.py + test_scan_hazards.py (без -k).
Каждая инъекция: одна правка, diff в diff-<ID>.patch, вывод в out-<ID>.txt, откат git checkout + git status пусто.

## Сводка

| № | ожидаемые красные | наблюдаемые красные | итог | совпало |
|---|---|---|---|---|
| I1 | T::blob_cache_reparses_only_changed_oids, T::one_git_process_per_scan, T::scanner_change_is_full_miss, T::unparsable_source_gives_error_facts, (T::facts_depend_only_on_content, если считает hits) | T::test_one_git_process_per_scan, T::test_blob_cache_reparses_only_changed_oids, T::test_scanner_change_is_full_miss, T::test_unparsable_source_gives_error_facts, H::test_broken_cache_body_is_miss_and_rewritten | 5 failed, 19 passed | нет: лишний H::test_broken_cache_body_is_miss_and_rewritten; T::facts_depend не красный (условный) |
| I2 | T::test_scanner_change_is_full_miss | T::test_blob_cache_reparses_only_changed_oids, T::test_scanner_change_is_full_miss, H::test_get_scans_chunks_over_500_oids | 3 failed, 21 passed | нет: лишние T::blob_cache_reparses, H::get_scans_chunks_over_500 |
| I3 | T::test_facts_depend_only_on_content | T::test_facts_depend_only_on_content | 1 failed, 23 passed | да |
| I4 | T::test_unparsable_source_gives_error_facts | T::test_unparsable_source_gives_error_facts, H::test_pathological_sources_isolated_from_neighbours | 2 failed, 22 passed | нет: лишний H::test_pathological_sources_isolated_from_neighbours |
| I5 | T::unparsable, H::pathological_sources_isolated | T::test_unparsable_source_gives_error_facts, H::test_pathological_sources_isolated_from_neighbours | 2 failed, 22 passed | да |
| I6 | T::test_import_kinds_hard_lazy_tc | T::test_import_kinds_hard_lazy_tc | 1 failed, 23 passed | да |
| I7 | T::test_guarded_relative_import_marked_guarded | T::test_guarded_relative_import_marked_guarded | 1 failed, 23 passed | да |
| I8 | T::test_class_methods_keep_dunder_members | T::test_class_methods_keep_dunder_members, H::test_json_round_trip_empty_and_full_tuples | 2 failed, 22 passed | нет: лишний H::test_json_round_trip_empty_and_full_tuples |
| I9 | T::test_one_git_process_per_scan | T::test_one_git_process_per_scan | 1 failed, 23 passed | да |
| I10 | T::test_one_git_process_per_scan | T::test_one_git_process_per_scan | 1 failed, 23 passed | да |
| I11 | T::test_one_git_process_per_scan, H::test_paths_with_space_cyrillic_newline_do_not_shift_batch | T::test_one_git_process_per_scan, H::test_paths_with_space_cyrillic_newline_do_not_shift_batch | 2 failed, 22 passed | да |
| I12 | T::test_from_pkg_import_submodule_targets_submodule | T::test_from_pkg_import_submodule_targets_submodule, T::test_init_level_one_is_package | 2 failed, 22 passed | нет: лишний T::test_init_level_one_is_package |
| I13 | T::test_init_level_one_is_package | T::test_init_level_one_is_package | 1 failed, 23 passed | да |
| I14 | T::test_unparsable_source_gives_error_facts | T::test_unparsable_source_gives_error_facts, H::test_blob_over_limit_not_decoded | 2 failed, 22 passed | нет: лишний H::test_blob_over_limit_not_decoded |
| I15 | T::test_tree_and_dict_source_give_equal_facts | T::test_tree_and_dict_source_give_equal_facts | 1 failed, 23 passed | да |
| I16 | T::test_commands_and_threads_literals | T::test_commands_and_threads_literals | 1 failed, 23 passed | да |
| I17 | T::test_all_plus_equals | T::test_all_plus_equals | 1 failed, 23 passed | да |
| I18 | T::test_header_tier_contour_parsed | T::test_header_tier_contour_parsed | 1 failed, 23 passed | да |
| I19 | нет (ожидаю 0) | H::test_get_scans_chunks_over_500_oids | 1 failed, 23 passed | нет: прогноз 0, тест ловит (ассерт на 3 SELECT) |
| I20 | нет (ожидаю 0) | нет | 0 failed, 24 passed | да |
| I21 | H::test_db_locked_by_writer_scan_still_returns_facts | H::test_db_locked_by_writer_scan_still_returns_facts | 1 failed, 23 passed | да |
| I22 | H::test_broken_cache_body_is_miss_and_rewritten | H::test_broken_cache_body_is_miss_and_rewritten | 1 failed, 23 passed | да |

## Diff каждой инъекции

### I1
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..222327205 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -403,7 +403,7 @@ def scan(source: Source, paths: Sequence[str], cache: sqlite3.Connection | None
     first_path: dict[str, str] = {}  # oid -> первый путь с этим блобом: два пути с одним oid разбираются один раз
     for p in present:
         first_path.setdefault(oids[p], p)
-    cached = get_scans(cache, scanner, list(first_path)) if cache is not None and first_path else {}
+    cached = {}
     for oid, body in cached.items():
         try:
             by_oid[oid] = FileFacts.from_json(body)
```
Результат: 5 failed, 19 passed; упали: T::test_one_git_process_per_scan, T::test_blob_cache_reparses_only_changed_oids, T::test_scanner_change_is_full_miss, T::test_unparsable_source_gives_error_facts, H::test_broken_cache_body_is_miss_and_rewritten

### I2
```diff
diff --git a/scripts/atlas/store.py b/scripts/atlas/store.py
index f744a3253..22173823a 100644
--- a/scripts/atlas/store.py
+++ b/scripts/atlas/store.py
@@ -203,8 +203,8 @@ def get_scans(con: sqlite3.Connection, scanner: str, oids: Iterable[str]) -> dic
         for i in range(0, len(wanted), _CHUNK):
             chunk = wanted[i : i + _CHUNK]
             marks = ", ".join("?" * len(chunk))
-            sql = f"SELECT oid, body FROM scan_cache WHERE scanner = ? AND oid IN ({marks})"
-            found.update(con.execute(sql, (scanner, *chunk)))
+            sql = f"SELECT oid, body FROM scan_cache WHERE oid IN ({marks})"
+            found.update(con.execute(sql, tuple(chunk)))
     except sqlite3.OperationalError as exc:
         print(f"atlas: кэш фактов не прочитан: {exc}", file=sys.stderr)
         return {}
```
Результат: 3 failed, 21 passed; упали: T::test_blob_cache_reparses_only_changed_oids, T::test_scanner_change_is_full_miss, H::test_get_scans_chunks_over_500_oids

### I3
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..0f391d982 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -426,7 +426,15 @@ def scan(source: Source, paths: Sequence[str], cache: sqlite3.Connection | None
 
     gone = [p for p in present if oids[p] not in by_oid]
     gone_set = set(gone)
-    facts_by_path = {p: by_oid[oids[p]] for p in present if p not in gone_set}
+    facts_by_path = {
+        p: (
+            by_oid[oids[p]]
+            if p.endswith("__init__.py")
+            else FileFacts(**{**by_oid[oids[p]].__dict__, "all": None, "doc": None, "tier": None, "contour": None})
+        )
+        for p in present
+        if p not in gone_set
+    }
     missing += gone
     return ScanResult(facts_by_path, tuple(missing), len(fresh), hits)
```
Результат: 1 failed, 23 passed; упали: T::test_facts_depend_only_on_content

### I4
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..447830547 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -304,7 +304,7 @@ def _loc(text: str) -> int:
 
 def scan_text(text: str) -> FileFacts:
     """Факты исходника; не бросает никогда. Зависят только от текста (R5): ни пути, ни `is_init`."""
-    text = text.removeprefix("﻿")
+    text = text
     try:
         loc = _loc(text)
     except Exception:  # noqa: BLE001 — контракт «не бросает»
```
Результат: 2 failed, 22 passed; упали: T::test_unparsable_source_gives_error_facts, H::test_pathological_sources_isolated_from_neighbours

### I5
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..91e6ecad3 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -335,7 +335,7 @@ def scan_text(text: str) -> FileFacts:
             tier=tier,
             contour=contour,
         )
-    except Exception as exc:  # noqa: BLE001 — SyntaxError, ValueError, RecursionError, MemoryError, ...
+    except (SyntaxError, ValueError, UnicodeDecodeError) as exc:  # noqa: BLE001 — SyntaxError, ValueError, RecursionError, MemoryError, ...
         return FileFacts(loc=loc, error=type(exc).__name__)
```
Результат: 2 failed, 22 passed; упали: T::test_unparsable_source_gives_error_facts, H::test_pathological_sources_isolated_from_neighbours

### I6
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..95f254889 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -174,7 +174,7 @@ def collect_imports(tree: ast.Module) -> tuple[ImportRec, ...]:
         elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
             # тело def выполняется позже: try вокруг него импорт не защищает;
             # под `if TYPE_CHECKING` функции в рантайме нет -> tc
-            visit(stmt, "tc" if kind == "tc" else "lazy", False)
+            visit(stmt, "lazy", False)
         else:
             visit(stmt, kind, guarded)
```
Результат: 1 failed, 23 passed; упали: T::test_import_kinds_hard_lazy_tc

### I7
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..ccb8c0ca9 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -166,7 +166,7 @@ def collect_imports(tree: ast.Module) -> tuple[ImportRec, ...]:
             for sub in stmt.orelse:
                 handle(sub, kind, guarded)
         elif isinstance(stmt, (ast.Try, ast.TryStar)):
-            protected = guarded or any(catches_import_error(h) for h in stmt.handlers)
+            protected = True
             for sub in stmt.body:
                 handle(sub, kind, protected)
             for sub in [*stmt.handlers, *stmt.orelse, *stmt.finalbody]:
```
Результат: 1 failed, 23 passed; упали: T::test_guarded_relative_import_marked_guarded

### I8
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..89d9f47df 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -293,7 +293,7 @@ def _is_dunder(name: str) -> bool:
 
 def _class_fact(node: ast.ClassDef, styles: dict[str, str]) -> ClassFact:
     names = (m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
-    methods = tuple(dict.fromkeys(n for n in names if not n.startswith("_") or _is_dunder(n)))
+    methods = tuple(dict.fromkeys(n for n in names if not n.startswith("_")))
     styles[node.name] = style = class_style(node, styles)
     return ClassFact(node.name, tuple(ast.unparse(b) for b in node.bases), node.lineno, methods, style)  # type: ignore[arg-type]
```
Результат: 2 failed, 22 passed; упали: T::test_class_methods_keep_dunder_members, H::test_json_round_trip_empty_and_full_tuples

### I9
```diff
diff --git a/scripts/atlas/tree.py b/scripts/atlas/tree.py
index 81bfa7c78..14e50dfbb 100644
--- a/scripts/atlas/tree.py
+++ b/scripts/atlas/tree.py
@@ -112,7 +112,7 @@ class Tree:
 
     def oids(self) -> dict[str, str]:
         """{путь: oid блоба} только для обычных файлов (режим 100644/100755)."""
-        return {path: oid for mode, oid, path in self._ls() if mode in ("100644", "100755")}
+        return {path: oid for mode, oid, path in self._ls()}
 
     def read_many(self, paths: Iterable[str]) -> dict[str, bytes | None]:
         """Содержимое файлов одним git-процессом; нет файла -> None, не исключение."""
```
Результат: 1 failed, 23 passed; упали: T::test_one_git_process_per_scan

### I10
```diff
diff --git a/scripts/atlas/tree.py b/scripts/atlas/tree.py
index 81bfa7c78..f132e8dd5 100644
--- a/scripts/atlas/tree.py
+++ b/scripts/atlas/tree.py
@@ -112,6 +112,7 @@ class Tree:
 
     def oids(self) -> dict[str, str]:
         """{путь: oid блоба} только для обычных файлов (режим 100644/100755)."""
+        self._entries = None  # собственный ls-tree, не общий с files()
         return {path: oid for mode, oid, path in self._ls() if mode in ("100644", "100755")}
 
     def read_many(self, paths: Iterable[str]) -> dict[str, bytes | None]:
```
Результат: 1 failed, 23 passed; упали: T::test_one_git_process_per_scan

### I11
```diff
diff --git a/scripts/atlas/tree.py b/scripts/atlas/tree.py
index 81bfa7c78..af91148e4 100644
--- a/scripts/atlas/tree.py
+++ b/scripts/atlas/tree.py
@@ -61,8 +61,6 @@ def read_blobs(root: str | Path, ref: str, paths: list[str], strict: bool = True
     """
     if not paths:
         return {}
-    if any("\n" in p for p in paths):
-        raise AtlasError("atlas: path with a newline cannot be read by cat-file --batch")
     proc = run_git(root, "cat-file", "--batch", input="".join(f"{ref}:{p}\n" for p in paths).encode("utf-8"))
     out: dict[str, bytes | None] = {}
     pos = 0
```
Результат: 2 failed, 22 passed; упали: T::test_one_git_process_per_scan, H::test_paths_with_space_cyrillic_newline_do_not_shift_batch

### I12
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..4f9b10e0d 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -494,6 +494,6 @@ class ImportIndex:
             return Resolved("internal", ((target, ()),))
         hits: dict[str, list[str]] = {}
         for name in rec.names:
-            sub = self._path_of.get(f"{base}.{name}") if self._is_init(target) else None
+            sub = None
             hits.setdefault(sub or target, []).append(name)  # `from pkg import sub` -> файл sub
         return Resolved("internal", tuple((p, tuple(names)) for p, names in hits.items()))
```
Результат: 2 failed, 22 passed; упали: T::test_from_pkg_import_submodule_targets_submodule, T::test_init_level_one_is_package

### I13
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..8cb52f4d1 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -440,7 +440,7 @@ def resolve_relative(level: int, module: str | None, current: str, is_init: bool
     У `__init__.py` одна точка — сам пакет, у обычного файла — его каталог.
     """
     base = current.split(".")
-    drop = level - 1 if is_init else level
+    drop = level
     if drop > len(base):
         return None
     trimmed = base[: len(base) - drop] if drop else base
```
Результат: 1 failed, 23 passed; упали: T::test_init_level_one_is_package

### I14
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..d67ac2b01 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -341,7 +341,7 @@ def scan_text(text: str) -> FileFacts:
 
 def _facts_of_bytes(data: bytes) -> FileFacts:
     """Байты блоба -> факты: предел размера ДО декодирования, потом utf-8 строго."""
-    if len(data) > MAX_BLOB_BYTES:
+    if len(data) >= MAX_BLOB_BYTES:
         return FileFacts(error="BlobTooLarge")
     try:
         text = data.decode("utf-8")
```
Результат: 2 failed, 22 passed; упали: T::test_unparsable_source_gives_error_facts, H::test_blob_over_limit_not_decoded

### I15
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..fb816a3ee 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -362,7 +362,7 @@ class Source(Protocol):
 
 
 def _blob_oid(data: bytes) -> str:
-    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
+    return hashlib.sha1(data).hexdigest()
 
 
 class DictSource:
```
Результат: 1 failed, 23 passed; упали: T::test_tree_and_dict_source_give_equal_facts

### I16
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..8766eeeb3 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -270,7 +270,7 @@ def collect_derived(tree: ast.Module) -> tuple[tuple[str, ...], tuple[tuple[str,
                     if kw.arg == "name":
                         threads.append((literal_str(kw.value) or ast.unparse(kw.value), node.lineno))
     threads.sort(key=lambda x: x[1])  # sort устойчив: порядок обхода внутри строки сохраняется
-    return tuple(sorted(commands)), tuple(threads)
+    return tuple(sorted(commands, reverse=True)), tuple(threads)
 
 
 def read_doc_headers(doc: str) -> tuple[str | None, tuple[str, ...] | None]:
```
Результат: 1 failed, 23 passed; упали: T::test_commands_and_threads_literals

### I17
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..175322912 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -218,7 +218,7 @@ def read_all(tree: ast.Module) -> tuple[str, ...] | None:
                 value = literal_names(stmt.value)
         elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "__all__":
             extra = literal_names(stmt.value) if isinstance(stmt.op, ast.Add) else None
-            value = None if value is None or extra is None else value + extra
+            value = value
         elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
             func = stmt.value.func  # __all__.extend(...) и т. п. — не разбираем, считаем не литералом
             if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "__all__":
```
Результат: 1 failed, 23 passed; упали: T::test_all_plus_equals

### I18
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..0da27d61a 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -281,7 +281,7 @@ def read_doc_headers(doc: str) -> tuple[str | None, tuple[str, ...] | None]:
         value = match.group(2).strip()
         if match.group(1) == "Tier":
             if tier is None and value.lower() in TIERS:
-                tier = value.lower()
+                tier = value
         elif contour is None:
             contour = tuple(x.strip() for x in value.split(",") if x.strip()) or None
     return tier, contour
```
Результат: 1 failed, 23 passed; упали: T::test_header_tier_contour_parsed

### I19
```diff
diff --git a/scripts/atlas/store.py b/scripts/atlas/store.py
index f744a3253..05313b881 100644
--- a/scripts/atlas/store.py
+++ b/scripts/atlas/store.py
@@ -189,7 +189,7 @@ def put_view(
         print(f"atlas: кэш вида не записан: {exc}", file=sys.stderr)
 
 
-_CHUNK = 500  # предел переменных в одном `IN (...)`
+_CHUNK = 1_000_000  # предел переменных в одном `IN (...)`
 
 
 def get_scans(con: sqlite3.Connection, scanner: str, oids: Iterable[str]) -> dict[str, str]:
```
Результат: 1 failed, 23 passed; упали: H::test_get_scans_chunks_over_500_oids

### I20
```diff
diff --git a/scripts/atlas/store.py b/scripts/atlas/store.py
index f744a3253..af241d918 100644
--- a/scripts/atlas/store.py
+++ b/scripts/atlas/store.py
@@ -214,10 +214,11 @@ def get_scans(con: sqlite3.Connection, scanner: str, oids: Iterable[str]) -> dic
 def put_scans(con: sqlite3.Connection, scanner: str, rows: Iterable[tuple[str, str]]) -> None:
     """Записать пары (oid, body) одной транзакцией; тот же ключ перезаписывается."""
     try:
-        with con:
-            con.executemany(
-                "INSERT OR REPLACE INTO scan_cache (oid, scanner, body) VALUES (?, ?, ?)",
-                [(oid, scanner, body) for oid, body in rows],
-            )
+        for oid, body in rows:
+            with con:
+                con.execute(
+                    "INSERT OR REPLACE INTO scan_cache (oid, scanner, body) VALUES (?, ?, ?)",
+                    (oid, scanner, body),
+                )
     except sqlite3.OperationalError as exc:  # база занята читателем: факты уже разобраны
         print(f"atlas: кэш фактов не записан: {exc}", file=sys.stderr)
```
Результат: 0 failed, 24 passed; упали: нет

### I21
```diff
diff --git a/scripts/atlas/store.py b/scripts/atlas/store.py
index f744a3253..8fde32b44 100644
--- a/scripts/atlas/store.py
+++ b/scripts/atlas/store.py
@@ -205,7 +205,7 @@ def get_scans(con: sqlite3.Connection, scanner: str, oids: Iterable[str]) -> dic
             marks = ", ".join("?" * len(chunk))
             sql = f"SELECT oid, body FROM scan_cache WHERE scanner = ? AND oid IN ({marks})"
             found.update(con.execute(sql, (scanner, *chunk)))
-    except sqlite3.OperationalError as exc:
+    except sqlite3.ProgrammingError as exc:
         print(f"atlas: кэш фактов не прочитан: {exc}", file=sys.stderr)
         return {}
     return found
```
Результат: 1 failed, 23 passed; упали: H::test_db_locked_by_writer_scan_still_returns_facts

### I22
```diff
diff --git a/scripts/atlas/scan.py b/scripts/atlas/scan.py
index b67b14afe..1d9531c11 100644
--- a/scripts/atlas/scan.py
+++ b/scripts/atlas/scan.py
@@ -405,10 +405,7 @@ def scan(source: Source, paths: Sequence[str], cache: sqlite3.Connection | None
         first_path.setdefault(oids[p], p)
     cached = get_scans(cache, scanner, list(first_path)) if cache is not None and first_path else {}
     for oid, body in cached.items():
-        try:
-            by_oid[oid] = FileFacts.from_json(body)
-        except Exception:  # noqa: BLE001 — битое тело кэша: промах, строку перезапишет put_scans
-            continue
+        by_oid[oid] = FileFacts.from_json(body)
     hits = len(by_oid)
 
     todo = {oid: p for oid, p in first_path.items() if oid not in by_oid}
```
Результат: 1 failed, 23 passed; упали: H::test_broken_cache_body_is_miss_and_rewritten

## Что оставил открытым / ненадёжным

- I3: флаг `all/doc/tier/contour` зависит от пути, а `scan_text` пути не видит. Правка сделана в `scan()` (только для не-`__init__.py`). Место выбрано мной, неоднозначно.
- I16: вместо простого `tuple(commands)` поставлен `sorted(..., reverse=True)`, чтобы порядок был детерминированным (порядок set зависит от хеша). Это выбор, не чистое удаление сортировки.
- I21: вместо удаления `try` поставлен `except sqlite3.ProgrammingError` (блокировка БД даёт OperationalError, он уходит наверх). Смысл тот же.
- I2: правка в `store.get_scans` (SQL без `scanner`); заодно параметр `scanner` стал неиспользуемым.
- I10: `self._entries = None` в `oids()`, поэтому `oids()` делает свой ls-tree, но и сбрасывает кэш `files()`.
- I19: прогноз был 0 красных, но `H::test_get_scans_chunks_over_500_oids` красный: тест ассертит ровно 3 SELECT (500+500+201), то есть ловит порции, а не только результат. Вывод: тест не вакуумный, прогноз ошибочен. Остаётся: при реальных >32766 параметрах (`_CHUNK=1_000_000`) был бы OperationalError, который в коде проглатывается в `{}`. Этот случай не покрыт тестами.
- I20: 0 красных, как прогнозировалось. Свойство времени не мерилось (это ожидаемо).
- Побочные ruff-замечания после правок (F401 unused get_scans в scan.py, F841 extra в scan.py): это последствия инъекций, не тесты; ruff в прогоне не запускался.
- Хук форматтера после правок писал «scan.py/store.py changed on disk»; после каждого отката `git status --short` пусто.
- pytest -rf печатает некоторые FAILED-строки дважды; в таблице имена уникальные.
- Коммитов и пушей не было. Все результаты получены прогонами в этой сессии, повторно не перепрогонялись (diff и out-файлы сохранены).
