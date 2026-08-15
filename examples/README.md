# Dual Embedder / RRF Retrieval Example

演示「general embedding + FinBERT 双索引 + Reciprocal Rank Fusion」的检索管线，
以及用 MRR 对比三种策略（`general` / `finbert` / `rrf`）的评测脚本。

## 依赖

示例是自包含的，不改动仓库现有依赖。需要额外安装：

```bash
python3 -m venv .venv-examples
source .venv-examples/bin/activate
pip install chromadb sentence-transformers transformers torch
```

首次运行会下载模型：

- `all-MiniLM-L6-v2`（general，约 90MB）
- `ProsusAI/finbert`（FinBERT，约 420MB）

## 运行

在仓库根目录：

```bash
python examples/dual_embedder.py --reset
```

`--reset` 会清空 `~/.finance_rag/chroma_rrf_demo` 并重新入库，方便反复演示。

输出包括：

1. 一条带 metadata 过滤的单查询结果（只搜 `credit_agreement`）。
2. 对 `examples/data/golden_set.json` 的 MRR@5 对比：

```text
== MRR@5 over 5 golden queries ==
  general     ...
  finbert     ...
  rrf         ...
```

## 说明与注意

- 两个 Chroma collection 共享同一套 chunk id，RRF 才能按 id 对齐融合。
- 示例里的 MRR 数字只用于演示流程；决定是否保留 FinBERT 那一支，必须用真实
  标注的 golden set（query + relevant chunk ids）评测。
- `ProsusAI/finbert` 是情感分类微调版，检索向量不是它的强项。想要「金融领域
  语义」可换成 `yiyanghkust/finbert-pretrain`：

  ```bash
  python examples/dual_embedder.py --finbert-model yiyanghkust/finbert-pretrain --reset
  ```

- 两个模型都偏英文；中文语料请把 general 换成
  `paraphrase-multilingual-MiniLM-L12-v2`，FinBERT 这支对中文基本无增益。

## 文件

- `dual_embedder.py`：完整脚本（FinBERT mean pooling、双索引、RRF、MRR 评测）。
- `data/sample_corpus.json`：小型金融样例语料（credit agreement / term sheet /
  10-K / research，含表格 chunk 和 metadata）。
- `data/golden_set.json`：5 条 golden Q&A，用于 MRR 对比。
