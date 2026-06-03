from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from app.core.config import settings
from app.core.logging import logger

_COLLECTION = "brand_embeddings"
_VECTOR_DIM = 384  # BAAI/bge-small-en-v1.5

_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    return _client


async def ensure_brand_embeddings_collection() -> None:
    client = get_qdrant_client()
    response = await client.get_collections()
    existing = {c.name for c in response.collections}
    if _COLLECTION not in existing:
        await client.create_collection(
            collection_name=_COLLECTION,
            vectors_config=VectorParams(size=_VECTOR_DIM, distance=Distance.COSINE),
        )
        logger.info("qdrant_collection_created", collection=_COLLECTION)
    else:
        logger.info("qdrant_collection_exists", collection=_COLLECTION)
