"""
NOVA — Neural Orchestration & Velocity Assistant
Supports two inference providers, switchable via NOVA_PROVIDER env var:
  - "ollama"    local Ollama (default)
  - "cerebras"  Cerebras cloud (~2000 tok/s, free tier)
"""
import httpx
import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer, CrossEncoder
    EMBEDDING_MODEL = SentenceTransformer(settings.embedding_model)
    RERANKER_MODEL  = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    _ST_AVAILABLE = True
except Exception as _e:
    logger.warning(f"sentence_transformers not available — embedding/rerank disabled: {_e}")
    EMBEDDING_MODEL = None
    RERANKER_MODEL  = None
    _ST_AVAILABLE = False

NOVA_SYSTEM_PROMPT = """You are NOVA, the built-in AI assistant for Trackly —
a work management platform used by engineering and cross-functional teams at 3SC Solutions.
Be concise, accurate, and helpful. When analysing tickets be specific.
When generating documents use markdown formatting.
Always ground your answers in the provided context when available."""


# ── Provider implementations ──────────────────────────────────────────────────

async def _chat_ollama(
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.nova_base_url}/api/chat",
            json={
                "model":   settings.nova_model,
                "messages": messages,
                "stream":  False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


async def _chat_cerebras(
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.cerebras_api_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       settings.cerebras_model,
                "messages":    messages,
                "temperature": temperature,
                "max_tokens":  max_tokens,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ── Public interface ──────────────────────────────────────────────────────────

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

    if settings.nova_provider == "cerebras":
        return await _chat_cerebras(messages, temperature, max_tokens)
    return await _chat_ollama(messages, temperature, max_tokens)


def embed(text: str) -> list[float]:
    if not _ST_AVAILABLE:
        raise RuntimeError("sentence_transformers not installed — AI embeddings unavailable")
    return EMBEDDING_MODEL.encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    if not _ST_AVAILABLE:
        raise RuntimeError("sentence_transformers not installed — AI embeddings unavailable")
    return EMBEDDING_MODEL.encode(
        texts, normalize_embeddings=True, batch_size=32
    ).tolist()


def rerank(query: str, documents: list[str], top_k: int = 5) -> list[int]:
    if not _ST_AVAILABLE:
        return list(range(min(top_k, len(documents))))
    pairs  = [(query, doc) for doc in documents]
    scores = RERANKER_MODEL.predict(pairs)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return ranked[:top_k]


async def analyze_image_with_llava(base64_image: str, description: str = "") -> dict:
    """
    Send a screenshot to the llava vision model via Ollama.
    Returns a structured dict: {title, description, repro_steps, severity, issue_type}.
    """
    import json as _json
    import re as _re

    desc_ctx = f'The user describes it as: "{description}".' if description.strip() else ""
    prompt = (
        f"You are a QA engineer. Analyze this screenshot for software bugs or UI issues. {desc_ctx}\n"
        "Return ONLY valid JSON — no prose, no markdown:\n"
        '{"title":"concise bug title","description":"what is wrong and why","'
        'repro_steps":["step 1","step 2","step 3"],'
        '"severity":"critical|high|medium|low","issue_type":"Bug|UI Bug|Performance|Crash"}'
    )

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{settings.nova_base_url}/api/generate",
            json={
                "model":  settings.vision_model,
                "prompt": prompt,
                "images": [base64_image],
                "stream": False,
            },
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")

    m = _re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return _json.loads(m.group())
        except Exception:
            pass

    # Fallback: use the raw text as description
    return {
        "title":       description[:80] if description else "Bug from screenshot",
        "description": raw or "Screenshot analysed — no structured fields extracted.",
        "repro_steps": [],
        "severity":    "medium",
        "issue_type":  "Bug",
    }


def is_available() -> bool:
    if settings.nova_provider == "cerebras":
        return bool(settings.cerebras_api_key)
    try:
        resp   = httpx.get(f"{settings.nova_base_url}/api/tags", timeout=3.0)
        models = [m["name"] for m in resp.json().get("models", [])]
        return any(settings.nova_model.split(":")[0] in m for m in models)
    except Exception:
        return False
