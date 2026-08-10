import json
import logging
import urllib.error
import urllib.request

import numpy as np

log = logging.getLogger("quality_classifier.embeddings")

OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768
TIMEOUT = 60


def embed(text: str) -> np.ndarray | None:
    text = (text or "").strip()
    if not text:
        return None

    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        log.warning(f"Ollama embed failed: {e}")
        return None

    vec = body.get("embedding")
    if not vec or len(vec) != EMBED_DIM:
        log.warning(f"Ollama returned unexpected embedding: dim={len(vec) if vec else 0}")
        return None
    return np.asarray(vec, dtype=np.float32)


def embed_batch(texts: list[str]) -> list[np.ndarray | None]:
    return [embed(t) for t in texts]


def ollama_alive() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False
