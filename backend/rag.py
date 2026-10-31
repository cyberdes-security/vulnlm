"""Real persistent Chroma index; deterministic hash embeddings avoid model downloads.

These embeddings exercise retrieval/tenant boundaries, not semantic quality benchmarks.
"""
import hashlib
import math
import re
from config import settings
from scenario_controls import enabled
from fastapi import HTTPException

_client = None
_collection = None

def embed(text):
    vector = [0.0] * 256
    for word in re.findall(r'\w+', text.casefold()):
        raw = hashlib.sha256(word.encode()).digest()
        vector[int.from_bytes(raw[:2], 'big') % 256] += 1
    length = math.sqrt(sum(x*x for x in vector)) or 1
    return [x / length for x in vector]

def collection():
    global _client, _collection
    if not settings.CHROMA_ENABLED:
        raise RuntimeError('RAG disabled; enable CHROMA_ENABLED for retrieval scenarios')
    if _collection is None:
        import chromadb
        _client = chromadb.PersistentClient(path=str(settings.DATA_DIR / 'chroma'))
        _collection = _client.get_or_create_collection('documents_v2', metadata={'hnsw:space': 'cosine'})
    return _collection

def ingest_document(title, content, source, user_id, doc_id=None, *, trusted=False):
    doc_id = str(doc_id or hashlib.sha256(f'{user_id}:{source}:{title}:{content}'.encode()).hexdigest())
    collection().upsert(ids=[doc_id], documents=[content], embeddings=[embed(title+' '+content)],
        metadatas=[{'title':title,'source':source,'owner_id':user_id,'trusted':bool(trusted)}])
    return doc_id

def retrieve_documents(query, n_results=3, actor_id=None):
    c = collection()
    count = c.count()
    if not count:
        return []
    filters = None
    if not enabled('rag-tenants'):
        if actor_id is None:
            raise HTTPException(403, 'Authenticated owner required for retrieval')
        filters = {'owner_id':actor_id}
    def search(where, size):
        r = c.query(query_embeddings=[embed(query)], n_results=min(count, size), where=where)
        return [{'id':i, 'content':d, **m}
                for i,d,m in zip(r['ids'][0],r['documents'][0],r['metadatas'][0])]

    if enabled('rag-rank-crowding'):
        # INTENTIONAL: similarity alone lets attacker documents occupy every slot.
        return search(filters, n_results)

    def scoped(trusted):
        trust_filter = {'trusted':trusted}
        return {'$and':[filters, trust_filter]} if filters else trust_filter

    # Query trust groups separately so a flood cannot push approved documents out of
    # the candidate window. Relevance order is retained inside each group; tenant
    # filtering applies before ranking. Bound work rather than scanning the index.
    window = min(100, max(n_results, n_results * 8))
    candidates = search(scoped(True), window) + search(scoped(False), window)
    unique = []
    seen = set()
    for doc in candidates:
        fingerprint = ' '.join(doc['content'].casefold().split())
        if fingerprint not in seen:
            unique.append(doc)
            seen.add(fingerprint)
        if len(unique) == n_results:
            break
    return unique

def reset_index():
    global _collection
    c = collection()
    _client.delete_collection(c.name)
    _collection = None
    collection()
