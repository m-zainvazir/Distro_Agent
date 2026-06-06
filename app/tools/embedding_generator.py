import asyncio

from sentence_transformers import SentenceTransformer

from app.core.logging import logger

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("loading_embedding_model", model=_MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _encode(text: str) -> list[float]:
    return _get_model().encode(text, normalize_embeddings=True).tolist()


def embed_text(text: str) -> list[float]:
    """Synchronous 384-dim embedding (normalized). Model is cached after first load.

    Used by the analyst's category scorer for semantic similarity. Kept sync so it
    can be injected into the (sync) scoring functions; callers in async contexts
    already run scoring in a tight per-store loop.
    """
    return _encode(text)


async def generate_brand_embedding(brand_profile_text: str) -> list[float]:
    """Generate a 384-dim embedding using BAAI/bge-small-en-v1.5 (local, free)."""
    return await asyncio.to_thread(_encode, brand_profile_text)
