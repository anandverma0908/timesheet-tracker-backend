"""
NOVA — Neural Orchestration & Velocity Assistant
Trackly's built-in AI. 100% local. Zero external API.
"""
import httpx
import logging
from sentence_transformers import SentenceTransformer, CrossEncoder
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = SentenceTransformer(settings.embedding_model)
RERANKER_MODEL  = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

NOVA_SYSTEM_PROMPT = """You are NOVA, the built-in AI assistant for Trackly —
a work management platform used by engineering and cross-functional teams at 3SC Solutions.
Be concise, accurate, and helpful. When analysing tickets be specific.
When generating documents use markdown formatting.
Always ground your answers in the provided context when available."""


async def chat(
    user_message: str,
    system_prompt: Optional[str] = None,
    context_docs: Optional[list[str]] = None,
    temperature: float = settings.nova_temperature,
    max_tokens: int = settings.nova_max_tokens,
) -> str:
    system = system_prompt or NOVA_SYSTEM_PROMPT
    if context_docs:
        context_block = "\n\n---\n\n".join(context_docs[:5])
        system += f"\n\n## Relevant context:\n\n{context_block}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_message},
    ]
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.nova_base_url}/api/chat",
            json={
                "model": settings.nova_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


def embed(text: str) -> list[float]:
    return EMBEDDING_MODEL.encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    return EMBEDDING_MODEL.encode(
        texts, normalize_embeddings=True, batch_size=32
    ).tolist()


def rerank(query: str, documents: list[str], top_k: int = 5) -> list[int]:
    pairs  = [(query, doc) for doc in documents]
    scores = RERANKER_MODEL.predict(pairs)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return ranked[:top_k]


def is_available() -> bool:
    try:
        resp   = httpx.get(f"{settings.nova_base_url}/api/tags", timeout=3.0)
        models = [m["name"] for m in resp.json().get("models", [])]
        return any(settings.nova_model.split(":")[0] in m for m in models)
    except Exception:
        return False
