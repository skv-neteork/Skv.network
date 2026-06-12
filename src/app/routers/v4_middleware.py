"""SKV v4.5 — Embeddings via FastEmbed (lightweight)"""
from fastembed import TextEmbedding

_model = None

def get_model():
    global _model
    if _model is None:
        _model = TextEmbedding(model_name='BAAI/bge-small-en-v1.5')
    return _model

def get_embedding(text: str) -> list:
    model = get_model()
    return list(model.embed([text]))[0].tolist()

def get_embedding_cached(text: str) -> list:
    return get_embedding(text)
