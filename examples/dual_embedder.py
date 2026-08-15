"""Dual-index retrieval demo: general embedding vs FinBERT vs RRF fusion.

Two Chroma collections share the same chunk ids / metadata:
  - fin_docs_general : sentence-transformers (general semantic embedding)
  - fin_docs_finbert : FinBERT mean-pooled token embeddings (domain signal)

Queries hit both collections, then Reciprocal Rank Fusion merges the two
rankings.  `evaluate_mrr` compares MRR@k for general / finbert / rrf against
a small golden set so you can decide whether the FinBERT leg is worth keeping.

Run from the repo root:
    python examples/dual_embedder.py --reset
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import torch
import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from sentence_transformers import SentenceTransformer
from transformers import AutoModel, AutoTokenizer


DATA_DIR = Path(__file__).resolve().parent / "data"


# ---------------------------------------------------------------
# FinBERT wrapper: BERT-style models need mean pooling for sentence vectors
# ---------------------------------------------------------------

class FinBertEmbedder:
    def __init__(self, model_name: str = "ProsusAI/finbert", max_length: int = 256):
        self.device = self._pick_device()
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(self.device).eval()
        self.max_length = max_length

    @staticmethod
    def _pick_device() -> str:
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def encode(self, texts: list[str]) -> np.ndarray:
        enc = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        ).to(self.device)
        with torch.no_grad():
            out = self.model(**enc)
        mask = enc["attention_mask"].unsqueeze(-1).float()
        pooled = (out.last_hidden_state * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        vec = pooled.cpu().numpy()
        return vec / np.linalg.norm(vec, axis=1, keepdims=True)


# ---------------------------------------------------------------
# Two embedding functions: one per collection
# ---------------------------------------------------------------

class GeneralEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def __call__(self, input: Documents) -> Embeddings:
        return self.model.encode(list(input), normalize_embeddings=True).tolist()


class FinBertEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name: str = "ProsusAI/finbert"):
        self.embedder = FinBertEmbedder(model_name)

    def __call__(self, input: Documents) -> Embeddings:
        return self.embedder.encode(list(input)).tolist()


# ---------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------

def reciprocal_rank_fusion(ranked_lists: list[list[str]], k: int = 60) -> list[str]:
    """Standard RRF: score(doc) = sum over lists of 1 / (k + rank)."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, 1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)


# ---------------------------------------------------------------
# Dual-index retriever
# ---------------------------------------------------------------

class DualIndexRetriever:
    def __init__(
        self,
        persist_dir: str = "~/.finance_rag/chroma_rrf_demo",
        general_model: str = "all-MiniLM-L6-v2",
        finbert_model: str = "ProsusAI/finbert",
    ):
        self.client = chromadb.PersistentClient(path=str(Path(persist_dir).expanduser()))
        self.general_col = self.client.get_or_create_collection(
            name="fin_docs_general",
            embedding_function=GeneralEmbeddingFunction(general_model),
            metadata={"hnsw:space": "cosine"},
        )
        self.finbert_col = self.client.get_or_create_collection(
            name="fin_docs_finbert",
            embedding_function=FinBertEmbeddingFunction(finbert_model),
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        # Both collections must share the same ids so RRF can align on them.
        self.general_col.upsert(ids=ids, documents=documents, metadatas=metadatas)
        self.finbert_col.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def _query_ids(self, col, query: str, top_k: int, where=None) -> list[str]:
        res = col.query(query_texts=[query], n_results=top_k, where=where)
        return res["ids"][0]

    def search(self, query: str, top_k: int = 5, where=None) -> list[tuple]:
        """Query each index (top_k*3 candidates), fuse with RRF, take top_k."""
        general_ids = self._query_ids(self.general_col, query, top_k * 3, where)
        finbert_ids = self._query_ids(self.finbert_col, query, top_k * 3, where)
        fused_ids = reciprocal_rank_fusion([general_ids, finbert_ids])[:top_k]

        if not fused_ids:
            return []
        got = self.general_col.get(ids=fused_ids, include=["documents", "metadatas"])
        return list(zip(got["ids"], got["documents"], got["metadatas"]))


# ---------------------------------------------------------------
# MRR evaluation
# ---------------------------------------------------------------

def reciprocal_rank(ranked_ids: list[str], relevant_ids: list[str]) -> float:
    relevant = set(relevant_ids)
    for rank, cid in enumerate(ranked_ids, 1):
        if cid in relevant:
            return 1.0 / rank
    return 0.0


def evaluate_mrr(
    retriever: DualIndexRetriever,
    golden: list[tuple[str, list[str]]],
    top_k: int = 5,
    where=None,
) -> dict[str, float]:
    """golden: [(query, [relevant_chunk_id, ...]), ...].  Returns MRR@top_k."""
    scores = {"general": [], "finbert": [], "rrf": []}

    for query, relevant in golden:
        general_ids = retriever._query_ids(retriever.general_col, query, top_k, where)
        finbert_ids = retriever._query_ids(retriever.finbert_col, query, top_k, where)
        fused_ids = [item[0] for item in retriever.search(query, top_k=top_k, where=where)]

        scores["general"].append(reciprocal_rank(general_ids, relevant))
        scores["finbert"].append(reciprocal_rank(finbert_ids, relevant))
        scores["rrf"].append(reciprocal_rank(fused_ids, relevant))

    return {name: round(float(np.mean(v)), 4) for name, v in scores.items()}


# ---------------------------------------------------------------
# Corpus / golden set loading (JSON data files in examples/data)
# ---------------------------------------------------------------

def load_corpus(path: Path | None = None) -> tuple[list[str], list[str], list[dict]]:
    if path is None:
        path = DATA_DIR / "sample_corpus.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["ids"], data["documents"], data["metadatas"]

    # Built-in fallback so the script still runs without the data files.
    ids = ["covenant_debt_limit", "covenant_leverage", "covenant_table", "term_sheet_terms"]
    documents = [
        "Negative Covenant: the borrower shall not incur additional indebtedness "
        "in excess of $500 million, except for permitted refinancings.",
        "Financial Covenant: Consolidated Leverage Ratio shall not exceed 4.50x, "
        "measured at each fiscal quarter end.",
        "| Covenant | Threshold |\n|---|---|\n| Leverage Ratio | 4.50x |\n"
        "| Interest Coverage | 2.50x |",
        "Term Sheet: Acme Refinancing, $1.2B senior secured notes, maturity 2029, "
        "priced at SOFR + 350bps, callable at 101.",
    ]
    metadatas = [
        {"deal_name": "Acme Refi", "document_type": "credit_agreement", "date": "2024-03-15", "chunk_type": "text"},
        {"deal_name": "Acme Refi", "document_type": "credit_agreement", "date": "2024-03-15", "chunk_type": "text"},
        {"deal_name": "Acme Refi", "document_type": "credit_agreement", "date": "2024-03-15", "chunk_type": "table"},
        {"deal_name": "Acme Refi", "document_type": "term_sheet", "date": "2024-03-15", "chunk_type": "text"},
    ]
    return ids, documents, metadatas


def load_golden(path: Path | None = None) -> list[tuple[str, list[str]]]:
    if path is None:
        path = DATA_DIR / "golden_set.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return [(item["query"], list(item["relevant_ids"])) for item in data]

    return [
        ("What is the additional indebtedness limit?", ["covenant_debt_limit"]),
        ("What is the maximum leverage ratio covenant?", ["covenant_leverage", "covenant_table"]),
        ("What margin is the refinancing priced at?", ["term_sheet_terms"]),
    ]


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="wipe the demo Chroma dir and re-index")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--persist-dir", default="~/.finance_rag/chroma_rrf_demo")
    parser.add_argument("--general-model", default="all-MiniLM-L6-v2")
    parser.add_argument("--finbert-model", default="ProsusAI/finbert")
    parser.add_argument("--corpus", default=None, help="path to sample_corpus.json")
    parser.add_argument("--golden", default=None, help="path to golden_set.json")
    args = parser.parse_args(argv)

    persist_dir = str(Path(args.persist_dir).expanduser())
    if args.reset:
        shutil.rmtree(persist_dir, ignore_errors=True)

    retriever = DualIndexRetriever(
        persist_dir=persist_dir,
        general_model=args.general_model,
        finbert_model=args.finbert_model,
    )

    ids, documents, metadatas = load_corpus(Path(args.corpus) if args.corpus else None)
    retriever.upsert(ids, documents, metadatas)
    print(f"indexed {len(ids)} chunks into general + finbert collections")

    print("\n== single query with metadata filter ==")
    hits = retriever.search(
        "What is the maximum leverage ratio covenant?",
        top_k=3,
        where={"document_type": "credit_agreement"},
    )
    for cid, doc, meta in hits:
        print(f"  {cid} [{meta['chunk_type']}] {doc[:90]}")

    golden = load_golden(Path(args.golden) if args.golden else None)
    print(f"\n== MRR@{args.top_k} over {len(golden)} golden queries ==")
    mrr = evaluate_mrr(retriever, golden, top_k=args.top_k)
    for name, value in mrr.items():
        print(f"  {name:<10} {value:>8.4f}")
    print("  (synthetic demo numbers only - label a real golden set for decisions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
