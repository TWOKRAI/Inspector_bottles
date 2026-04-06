# Supported Languages

qex uses tree-sitter grammars for language-aware code chunking. Each language has a dedicated chunker that understands its syntax and extracts semantic units.

## Language Table

| Language | Extensions | Chunk Types |
|----------|-----------|-------------|
| Python | `.py`, `.pyi` | function, method, class, decorated_definition |
| JavaScript | `.js` | function, method, class |
| TypeScript | `.ts`, `.tsx` | function, method, class, interface |
| Rust | `.rs` | function, method, struct, enum, trait, impl, macro |
| Go | `.go` | function, method, struct, interface |
| Java | `.java` | method, class, interface, enum |
| C | `.c`, `.h` | function, struct |
| C++ | `.cpp`, `.cc`, `.cxx`, `.hpp` | function, method, class, struct, namespace |
| C# | `.cs` | method, class, struct, interface, enum, namespace |
| Markdown | `.md` | section, document |

## Chunk Types

| Type | Description |
|------|-------------|
| `Function` | Standalone function |
| `Method` | Function inside a class/struct/impl |
| `Class` | Class definition with body |
| `Struct` | Struct/record definition |
| `Trait` | Rust trait definition |
| `Interface` | Interface definition (TS, Go, Java, C#) |
| `Enum` | Enum definition |
| `Impl` | Rust impl block |
| `Macro` | Rust macro definition |
| `Module` | Module-level code |
| `Section` | Markdown section (split by headings) |
| `Other` | Unclassified code |

## Language-Specific Details

### Python

Extracts functions, methods, classes, and decorated definitions. Docstrings are extracted from triple-quoted strings immediately following the definition. Decorators (`@app.route`, `@pytest.fixture`, etc.) are captured.

### Rust

The most detailed chunker. Extracts functions, methods, structs, enums, traits, impl blocks, and macros. Doc comments (`///` and `//!`) are captured as docstrings. `#[derive(...)]` and other attributes are captured as decorators.

### TypeScript / TSX

Handles both `.ts` and `.tsx` files. Extracts functions, methods, classes, and interfaces. Type annotations are preserved in chunk content.

### Go

Extracts functions (including methods with receivers), structs, and interfaces. Method receivers are parsed to associate methods with their types.

### C / C++

C extracts functions and structs. C++ adds methods, classes, and namespaces. Header files (`.h`, `.hpp`) are fully supported.

### Markdown

Splits documents by headings into sections. Each section becomes a chunk with the heading as the name and the section body as content.

## Adding Language Support

Language support is implemented via the `LanguageChunker` trait in `qex-core/src/chunk/languages/mod.rs`. Each language implementation provides:

1. A tree-sitter grammar
2. Node type mappings (which AST nodes represent functions, classes, etc.)
3. Name extraction logic
4. Optional docstring/decorator extraction
