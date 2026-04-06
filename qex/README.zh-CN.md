<h1 align="center">QEX</h1>

<p align="center">
  <strong>轻量级 MCP 语义代码搜索服务器</strong>
</p>

<p align="center">
  BM25 + 可选稠密向量 + tree-sitter 代码分块
</p>

<p align="center">
  <a href="https://crates.io/crates/qex-mcp"><img src="https://img.shields.io/crates/v/qex-mcp.svg" alt="crates.io"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue.svg" alt="License: AGPL-3.0"></a>
  <a href="https://www.rust-lang.org/"><img src="https://img.shields.io/badge/Rust-2021_edition-orange.svg" alt="Rust"></a>
</p>

<p align="center">
  <a href="README.md">English</a> | <strong>中文</strong>
</p>

---

QEX 是一个用 Rust 构建的高性能 MCP 语义代码搜索服务器。将 BM25 全文检索与可选的稠密向量嵌入相结合，实现混合检索 —— 仅需一个约 19 MB 的二进制文件，即可提供媲美 Cursor 的搜索质量。Tree-sitter 解析理解代码结构（函数、类、方法），Merkle DAG 变更检测支持增量索引，一切在本地运行，零云端依赖。

## 最新特性

- **可插拔嵌入后端** —— 基于 trait 的抽象层，支持 ONNX Runtime（本地）和 OpenAI API 嵌入提供者，通过环境变量配置
- **混合搜索** —— BM25 + 稠密向量搜索，通过倒数排名融合（RRF）比纯稠密检索准确率高 48%
- **10 种语言支持** —— Python、JavaScript、TypeScript、Rust、Go、Java、C、C++、C#、Markdown，基于 tree-sitter
- **增量索引** —— 基于 Merkle DAG 的变更检测，仅重新索引发生变化的文件
- **可选稠密向量** —— snowflake-arctic-embed-s（33 MB，384 维，INT8 量化）通过 ONNX Runtime，或 OpenAI text-embedding-3-small 通过 API
- **原生 MCP 支持** —— 通过 stdio 作为工具服务器直接接入 Claude Code

## 为什么选择 QEX？

Claude Code 使用 grep + glob 进行代码搜索 —— 虽然有效，但消耗大量 token 且缺乏语义理解。Cursor 使用向量嵌入配合云端索引（约 3.5 GB）。**QEX** 是两者的折中方案：

- **BM25 + 稠密混合检索**：比纯稠密检索准确率高 48%（[Superlinked 2025](https://superlinked.com/vectorhub/articles/optimizing-rag-with-hybrid-search-reranking)）
- **Tree-sitter 代码分块**：理解代码结构 —— 函数、类、方法 —— 而非简单的行级别搜索
- **增量索引**：基于 Merkle DAG 的变更检测，仅重新索引发生变化的文件
- **零云端依赖**：一切通过 ONNX Runtime 在本地运行
- **原生 MCP 支持**：作为工具服务器直接接入 Claude Code

## 快速开始

**从 crates.io 安装：**

```bash
cargo install qex-mcp

# 添加到 Claude Code
claude mcp add qex --scope user -- ~/.cargo/bin/qex
```

**从源码构建：**

```bash
# 构建（仅 BM25，约 19 MB）
cargo build --release

# 或包含稠密向量搜索（约 36 MB）
cargo build --release --features dense

# 或包含 OpenAI 嵌入支持
cargo build --release --features openai

# 或包含所有嵌入后端
cargo build --release --features "dense,openai"

# 安装
cp target/release/qex ~/.local/bin/

# 添加到 Claude Code
claude mcp add qex --scope user -- ~/.local/bin/qex
```

完成。Claude 现在可以使用 `search_code` 和 `index_codebase` 工具了。

### 启用稠密搜索（可选）

稠密搜索增加了语义理解能力 —— 即使代码中写的是 `verify_token`，也能通过搜索"身份验证中间件"找到它。支持两种嵌入后端：

#### 方案 A：本地 ONNX 模型（推荐）

需要 `dense` 特性标志。零云端依赖。

```bash
# 下载嵌入模型（约 33 MB）
./scripts/download-model.sh

# 或通过 MCP 工具下载（添加到 Claude 后）
# Claude："下载嵌入模型"
```

**模型**：[snowflake-arctic-embed-s](https://huggingface.co/Snowflake/snowflake-arctic-embed-s) —— 384 维，INT8 量化，最大 512 token。

当模型存在时，搜索自动切换到混合模式。无需额外配置。

#### 方案 B：OpenAI API 嵌入

需要 `openai` 特性标志和 API 密钥。支持任何 OpenAI 兼容的 API。

```bash
# 使用 OpenAI 嵌入构建（可与 dense 组合）
cargo build --release --features "dense,openai"

# 配置
export QEX_EMBEDDING_PROVIDER=openai
export QEX_OPENAI_API_KEY=sk-...  # 或设置 OPENAI_API_KEY
```

**安全特性：** SSRF 防护（仅允许 HTTPS 或 localhost）、API 密钥脱敏、指数退避重试（429/5xx/超时）。

## 架构

```
Claude Code ──(stdio/JSON-RPC)──▶ qex
                                      │
                      ┌───────────────┼───────────────┐
                      ▼               ▼               ▼
                 tree-sitter      tantivy        ort + usearch
                  代码分块         BM25检索       稠密向量检索
                 (11种语言)       (<1ms)          (可选)
                      │               │               │
                      └───────┬───────┘               │
                              ▼                       │
                         排序引擎  ◄──────────────────┘
                    (RRF + 多因子排序)
                              │
                              ▼
                         排序后的结果
```

### 搜索流程

1. **查询分析** —— 分词、停用词过滤、意图识别
2. **BM25 搜索** —— 通过 tantivy 进行全文检索，支持字段级别权重（名称、内容、标签、路径）
3. **稠密搜索** _（可选）_ —— 查询向量化 → HNSW 余弦相似度 → top-k 结果
4. **倒数排名融合（RRF）** —— 合并 BM25 和稠密搜索结果：`score = Σ 1/(k + rank)`
5. **多因子重排序** —— 按代码块类型、名称匹配度、路径相关性、标签、文档字符串等重新排序
6. **测试文件降权** —— 测试文件权重降低至 0.7 倍，优先展示实现代码

### 索引流程

1. **文件遍历** —— 遵循 `.gitignore` 规则，支持按扩展名过滤
2. **Tree-sitter 解析** —— 语言感知的 AST 遍历，提取函数/类/方法
3. **代码块增强** —— 自动标签（async、auth、database...）、复杂度评分、文档字符串、装饰器
4. **BM25 索引** —— 14 字段 tantivy schema，字段级别权重
5. **稠密索引** _（可选）_ —— 批量嵌入（64 块/批次）→ HNSW 索引
6. **Merkle 快照** —— SHA-256 DAG，用于增量变更检测

## MCP 工具

### `index_codebase`
对项目进行索引以支持语义搜索。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 项目目录的绝对路径 |
| `force` | boolean | 否 | 强制完整重建索引（默认：false） |
| `extensions` | string[] | 否 | 仅索引指定扩展名，如 `["py", "rs"]` |

返回文件数、代码块数、检测到的语言和耗时。

### `search_code`
使用自然语言或关键词搜索已索引的代码库。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 项目目录的绝对路径 |
| `query` | string | 是 | 搜索查询（自然语言或关键词） |
| `limit` | integer | 否 | 最大结果数（默认：10） |
| `extension_filter` | string | 否 | 按扩展名过滤，如 `"py"` |

如果尚未索引会自动触发索引。返回带有代码片段、文件路径、行号和相关性评分的排序结果。

### `get_indexing_status`
检查项目是否已索引并获取统计信息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 项目目录的绝对路径 |

返回索引状态、文件/代码块数量、语言列表以及稠密搜索是否可用。

### `clear_index`
删除项目的所有索引数据。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 项目目录的绝对路径 |

### `download_model`
下载用于稠密搜索的嵌入模型。需要启用 `dense` 特性。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `force` | boolean | 否 | 即使已存在也重新下载（默认：false） |

## 支持的语言

| 语言 | 文件扩展名 | 代码块类型 |
|------|-----------|-----------|
| Python | `.py`, `.pyi` | 函数、方法、类、模块级代码、导入 |
| JavaScript | `.js` | 函数、方法、类、模块级代码 |
| TypeScript | `.ts`, `.tsx` | 函数、方法、类、接口、模块级代码 |
| Rust | `.rs` | 函数、方法、结构体、枚举、trait、impl、宏 |
| Go | `.go` | 函数、方法、结构体、接口 |
| Java | `.java` | 方法、类、接口、枚举 |
| C | `.c`, `.h` | 函数、结构体 |
| C++ | `.cpp`, `.cc`, `.cxx`, `.hpp` | 函数、方法、类、结构体、命名空间 |
| C# | `.cs` | 方法、类、结构体、接口、枚举、命名空间 |
| Markdown | `.md` | 章节、文档 |

## Crates

| 包 | 说明 | |
|----|------|-|
| [`qex-core`](crates/qex-core) | 核心库：代码分块、搜索、索引、Merkle DAG | [![crates.io](https://img.shields.io/crates/v/qex-core.svg)](https://crates.io/crates/qex-core) |
| [`qex-mcp`](crates/qex-mcp) | MCP 服务器二进制（通过 rmcp 的 stdio 传输） | [![crates.io](https://img.shields.io/crates/v/qex-mcp.svg)](https://crates.io/crates/qex-mcp) |

## 项目结构

```
qex/
├── Cargo.toml                        # 工作区根配置
├── scripts/
│   └── download-model.sh             # 模型下载脚本
├── crates/
│   ├── qex-core/            # 核心库
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── chunk/                # Tree-sitter 代码分块引擎
│   │       │   ├── tree_sitter.rs    # AST 遍历
│   │       │   ├── multi_language.rs # 多语言调度器
│   │       │   └── languages/        # 11 种语言实现
│   │       ├── search/               # 搜索引擎
│   │       │   ├── bm25.rs           # Tantivy BM25 索引
│   │       │   ├── dense.rs          # HNSW 向量索引（dense 特性）
│   │       │   ├── embedding.rs      # Embedder trait + ONNX 后端（dense|openai 特性）
│   │       │   ├── openai_embedder.rs # OpenAI API 后端（openai 特性）
│   │       │   ├── hybrid.rs         # 倒数排名融合（dense 特性）
│   │       │   ├── ranking.rs        # 多因子重排序
│   │       │   └── query.rs          # 查询分析
│   │       ├── index/                # 增量索引器
│   │       │   ├── mod.rs            # 主索引逻辑
│   │       │   └── storage.rs        # 项目存储布局
│   │       ├── merkle/               # 变更检测
│   │       │   ├── mod.rs            # Merkle DAG
│   │       │   ├── change_detector.rs
│   │       │   └── snapshot.rs
│   │       └── ignore.rs             # 遵循 gitignore 的文件遍历
│   │
│   └── qex-mcp/            # MCP 服务器二进制
│       └── src/
│           ├── main.rs               # 入口点，stdio 传输
│           ├── server.rs             # 工具处理器
│           ├── tools.rs              # 参数 schema
│           └── config.rs             # 命令行参数
│
└── tests/fixtures/                   # 测试用源文件
```

## 数据存储

所有数据存储在本地 `~/.qex/` 目录下：

```
~/.qex/
├── projects/
│   └── {项目名}_{哈希}/          # 每个项目的索引
│       ├── tantivy/              # BM25 索引
│       ├── dense/                # 向量索引（可选）
│       ├── snapshot.json         # Merkle DAG
│       └── stats.json            # 索引统计
│
└── models/
    └── arctic-embed-s/           # 嵌入模型（可选）
        ├── model.onnx            # 33 MB，INT8 量化
        └── tokenizer.json
```

## 构建与测试

```bash
# 运行测试（仅 BM25）
cargo test                              # 41 个测试

# 运行测试（包含稠密搜索）
cargo test --features dense             # 48 个测试

# 运行测试（包含 OpenAI 嵌入）
cargo test --features openai            # 50 个测试

# 运行测试（所有特性）
cargo test --features "dense,openai"    # 55 个测试

# 构建发布版本
cargo build --release                   # 约 19 MB
cargo build --release --features dense  # 约 36 MB
cargo build --release --features "dense,openai"  # 所有嵌入后端
```

## 核心依赖

| 库 | 版本 | 用途 |
|----|------|------|
| tantivy | 0.22 | BM25 全文检索 |
| tree-sitter | 0.24 | 代码解析（11 种语言） |
| rmcp | 0.17 | MCP 服务器框架（stdio） |
| rusqlite | 0.32 | SQLite 元数据（内置） |
| ignore | 0.4 | 遵循 gitignore 的文件遍历 |
| rayon | 1.10 | 并行代码分块 |
| ort | 2.0.0-rc.11 | ONNX Runtime _（可选，`dense`）_ |
| usearch | 2.24 | HNSW 向量索引 _（可选，`dense`）_ |
| tokenizers | 0.22 | HuggingFace 分词器 _（可选，`dense`）_ |
| ureq | 3 | 同步 HTTP 客户端 _（可选，`openai`）_ |

## 性能指标

在 Apple Silicon Mac 上的基准测试：

| 指标 | 数值 |
|------|------|
| 完整索引（400 块） | 含稠密搜索约 20 秒，仅 BM25 约 2 秒 |
| 增量索引（无变更） | <100 毫秒 |
| BM25 搜索 | <5 毫秒 |
| 混合搜索 | 约 50 毫秒（含嵌入计算） |
| 二进制大小 | 19 MB（BM25）/ 36 MB（稠密搜索） |
| 模型大小 | 33 MB（INT8 量化） |

## 许可证

[AGPL-3.0](LICENSE)
