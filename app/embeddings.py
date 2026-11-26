from functools import lru_cache

from fastembed import TextEmbedding

from app.config import settings

MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384 dimensions, runs on CPU


@lru_cache(maxsize=1)
def get_model():
    return TextEmbedding(model_name=MODEL_NAME, cache_dir=settings.model_cache_dir)


def embed_texts(texts):
    return [v.tolist() for v in get_model().embed(texts)]


def to_pgvector(vec):
    """[0.1, 0.2] -> '[0.100000,0.200000]', the text format pgvector accepts."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"