from __future__ import annotations
from sentence_transformers import SentenceTransformer
from .base import BaseEmbedder


class BGEM3Embedder(BaseEmbedder):
    def __init__(self, model_name: str = "BAAI/bge-m3", device: str | None = None):
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device=device)

    def embed(self, text: str) -> list[float]:
        return self.model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self.model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).tolist()
