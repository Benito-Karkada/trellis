"""Portable hybrid search for course discussions.

The default encoder is intentionally local and deterministic: it maps common
course vocabulary into semantic concepts, hashes token and character features,
and returns a normalized dense vector.  The provider boundary allows a learned embedding model later without changing
indexing or ranking.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.db import DatabaseError, connection, transaction

from .models import (DiscussionAnswer, DiscussionReply, DiscussionSearchDocument,
    DiscussionThread)


EMBEDDING_DIMENSIONS = 192
TOKEN_RE = re.compile(r"[a-z0-9_+#.-]+")
MARKUP_RE = re.compile(r"[`*_>#\[\](){}]+")

PHRASES = {
    "sign in": "login", "sign-in": "login", "log in": "login",
    "logged in": "login", "set up": "setup", "home work": "homework",
    "due date": "deadline", "turn in": "submit", "hand in": "submit",
    "does not work": "broken", "not working": "broken",
}

CONCEPTS = {
    "login": {"login", "signin", "authentication", "authenticate", "credential", "password"},
    "error": {"error", "exception", "failure", "failed", "failing", "crash", "broken", "bug"},
    "missing": {"missing", "absent", "unavailable", "lost", "empty", "cannotfind", "notfound"},
    "setup": {"setup", "install", "installation", "configure", "configuration", "environment", "dependency"},
    "file": {"file", "document", "folder", "directory", "path"},
    "package": {"package", "module", "library", "import", "dependency"},
    "assignment": {"assignment", "homework", "hw", "problem", "exercise", "project"},
    "assessment": {"quiz", "test", "exam", "assessment"},
    "deadline": {"deadline", "due", "late", "extension"},
    "submit": {"submit", "submission", "upload", "turnin", "handin"},
    "grade": {"grade", "score", "points", "credit", "mark"},
    "loop": {"loop", "iterate", "iteration", "repeat", "repetition"},
    "function": {"function", "method", "procedure", "callable"},
    "variable": {"variable", "value", "assignment", "identifier"},
    "list": {"list", "array", "sequence", "collection"},
    "dictionary": {"dictionary", "dict", "mapping", "map", "keyvalue"},
    "output": {"output", "print", "display", "result"},
    "input": {"input", "argument", "parameter", "prompt"},
    "runtime": {"runtime", "execute", "execution", "run", "running"},
    "syntax": {"syntax", "parse", "parsing", "indentation", "indent"},
    "infinite": {"infinite", "forever", "hang", "freeze", "stuck"},
    "understand": {"understand", "explain", "clarify", "confused", "meaning"},
}
CANONICAL = {word: concept for concept, words in CONCEPTS.items() for word in words}
CONCEPT_INDEX = {concept: index for index, concept in enumerate(CONCEPTS)}
HASH_OFFSET = len(CONCEPT_INDEX)


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


class LocalSemanticEmbeddingProvider:
    """Dependency-free encoder suitable for the local proof of concept."""
    name = "local-semantic-v2"
    dimensions = EMBEDDING_DIMENSIONS

    @staticmethod
    def _index(feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        number = int.from_bytes(digest, "big")
        return HASH_OFFSET + number % (EMBEDDING_DIMENSIONS - HASH_OFFSET), 1.0 if number & (1 << 63) else -1.0

    def embed(self, text: str) -> list[float]:
        cleaned = normalize_text(text)
        raw = TOKEN_RE.findall(cleaned)
        canonical = [CANONICAL.get(token, _stem(token)) for token in raw]
        features: list[tuple[str, float]] = []
        features.extend((f"word:{token}", 2.2) for token in canonical)
        features.extend((f"pair:{left}:{right}", 1.0) for left, right in zip(canonical, canonical[1:]))
        for token in canonical:
            padded = f"^{token}$"
            features.extend((f"char:{padded[index:index + 3]}", .18)
                for index in range(max(0, len(padded) - 2)))
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for token in canonical:
            if token in CONCEPT_INDEX: vector[CONCEPT_INDEX[token]] += 4.0
        for feature, weight in features:
            index, sign = self._index(feature)
            vector[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


_provider: EmbeddingProvider | None = None


def embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        provider_name = getattr(settings, "DISCUSSION_EMBEDDING_PROVIDER", "local")
        if provider_name != "local":
            raise ValueError(f"Unsupported discussion embedding provider: {provider_name}")
        _provider = LocalSemanticEmbeddingProvider()
    return _provider


def normalize_text(text: str) -> str:
    value = MARKUP_RE.sub(" ", text.lower())
    for phrase, replacement in PHRASES.items():
        value = re.sub(rf"\b{re.escape(phrase)}\b", replacement, value)
    value = re.sub(r"\b(?:can(?:not|'t)|unable to)\s+(?:find|locate)\b", "cannotfind", value)
    value = re.sub(r"\bnot\s+found\b", "notfound", value)
    return " ".join(value.split())


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("ing"): return token[:-3]
    if len(token) > 4 and token.endswith("ed"): return token[:-2]
    if len(token) > 4 and token.endswith("es"): return token[:-2]
    if len(token) > 3 and token.endswith("s"): return token[:-1]
    return token


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def parse_vector(value: str) -> list[float]:
    try: return [float(item) for item in value.strip()[1:-1].split(",")]
    except (TypeError, ValueError): return []


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left: return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def _save_document(thread: DiscussionThread, content_type: str, object_id: int,
        source_label: str, content: str) -> None:
    digest = hashlib.sha256((embedding_provider().name + "\0" + content).encode("utf-8")).hexdigest()
    existing = DiscussionSearchDocument.objects.filter(thread=thread, content_type=content_type,
        object_id=object_id).first()
    if existing and existing.content_hash == digest and existing.content == content: return
    embedding = vector_literal(embedding_provider().embed(content))
    DiscussionSearchDocument.objects.update_or_create(thread=thread, content_type=content_type,
        object_id=object_id, defaults={"course": thread.course, "source_label": source_label,
            "content": content, "embedding": embedding, "content_hash": digest})


def _thread_content(thread: DiscussionThread) -> str:
    folders = " ".join(thread.folders.values_list("name", flat=True))
    return f"{thread.title}\n{thread.body}" + (f"\nFolders: {folders}" if folders else "")


def refresh_thread_index(thread_id: int) -> None:
    thread = DiscussionThread.objects.filter(pk=thread_id, deleted_at=None).prefetch_related(
        "folders", "answers", "replies").first()
    if not thread:
        DiscussionSearchDocument.objects.filter(thread_id=thread_id).delete()
        return
    keep: set[tuple[str, int]] = {("post", thread.pk)}
    _save_document(thread, "post", thread.pk, "Post", _thread_content(thread))
    for answer in thread.answers.all():
        keep.add(("answer", answer.pk))
        label = "Instructor answer" if answer.kind == "instructor" else "Students’ answer"
        _save_document(thread, "answer", answer.pk, label, answer.body)
    for reply in thread.replies.all():
        if reply.deleted_at is not None: continue
        keep.add(("followup", reply.pk))
        _save_document(thread, "followup", reply.pk,
            "Followup reply" if reply.parent_id else "Followup", reply.body)
    stale = DiscussionSearchDocument.objects.filter(thread=thread)
    for document in stale.only("pk", "content_type", "object_id"):
        if (document.content_type, document.object_id) not in keep: document.delete()


def sync_course_index(course_id: int) -> None:
    thread_ids = list(DiscussionThread.objects.filter(course_id=course_id, deleted_at=None)
        .values_list("pk", flat=True))
    for thread_id in thread_ids: refresh_thread_index(thread_id)
    DiscussionSearchDocument.objects.filter(course_id=course_id).exclude(thread_id__in=thread_ids).delete()


def schedule_thread_index(thread_id: int) -> None:
    """Index synchronously in tests, or use Celery when enabled locally."""
    if getattr(settings, "DISCUSSION_SEARCH_ASYNC", False):
        from .tasks import refresh_discussion_search
        transaction.on_commit(lambda: refresh_discussion_search.delay(thread_id))
    else:
        refresh_thread_index(thread_id)


def _lexical_score(query: str, document: DiscussionSearchDocument) -> float:
    needle = normalize_text(query)
    haystack = normalize_text(document.content)
    raw_terms = TOKEN_RE.findall(needle)
    if not raw_terms: return 0.0
    counts = Counter(TOKEN_RE.findall(haystack))
    score = 0.0
    if needle in haystack: score += 9.0
    score += 4.0 * sum(1 for term in raw_terms if counts[term]) / len(raw_terms)
    score += min(2.0, sum(min(counts[term], 2) for term in raw_terms) * .35)
    if document.content_type == "post":
        title = normalize_text(document.content.split("\n", 1)[0])
        if needle in title: score += 5.0
        score += 1.5 * sum(1 for term in raw_terms if term in TOKEN_RE.findall(title)) / len(raw_terms)
    return score


def _postgres_cosine(documents: list[DiscussionSearchDocument], query_vector: list[float]) -> dict[int, float]:
    if connection.vendor != "postgresql" or not documents: return {}
    table = connection.ops.quote_name(DiscussionSearchDocument._meta.db_table)
    ids = [document.pk for document in documents]
    literal = vector_literal(query_vector)
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"SELECT id, embedding::vector({EMBEDDING_DIMENSIONS}) <=> %s::vector({EMBEDDING_DIMENSIONS}) AS distance "
                f"FROM {table} WHERE id = ANY(%s)",
                [literal, ids])
            return {row[0]: 1.0 - float(row[1]) for row in cursor.fetchall()}
    except DatabaseError:
        # A fresh developer database may be between image and migration updates.
        return {}


def _excerpt(content: str, query: str, limit: int = 190) -> str:
    plain = " ".join(MARKUP_RE.sub(" ", content).split())
    lowered = plain.lower()
    positions = [lowered.find(term) for term in TOKEN_RE.findall(query.lower())]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - 55)
    end = min(len(plain), start + limit)
    if start: start = plain.find(" ", start) + 1
    if end < len(plain): end = plain.rfind(" ", start, end)
    return ("…" if start else "") + plain[start:end].strip() + ("…" if end < len(plain) else "")


@dataclass(frozen=True)
class SearchMatch:
    thread_id: int
    score: float
    source: str
    excerpt: str


def search_discussions(query: str, course_id: int, thread_ids: list[int]) -> list[SearchMatch]:
    """Return best content match per already-authorized thread."""
    if not query.strip() or not thread_ids: return []
    # Mutations refresh their own index. Only backfill legacy/imported posts here;
    # typing a draft must not re-encode every post and answer in the course.
    indexed = DiscussionSearchDocument.objects.filter(course_id=course_id,
        content_type="post").values("thread_id")
    missing = DiscussionThread.objects.filter(course_id=course_id, pk__in=thread_ids,
        deleted_at=None).exclude(pk__in=indexed).values_list("pk", flat=True)
    for thread_id in missing:
        refresh_thread_index(thread_id)
    documents = list(DiscussionSearchDocument.objects.filter(course_id=course_id,
        thread_id__in=thread_ids).order_by("pk"))
    query_vector = embedding_provider().embed(query)
    semantic = _postgres_cosine(documents, query_vector)
    if not semantic:
        semantic = {document.pk: cosine(query_vector, parse_vector(document.embedding)) for document in documents}
    best: dict[int, SearchMatch] = {}
    for document in documents:
        lexical = _lexical_score(query, document)
        semantic_score = max(0.0, semantic.get(document.pk, 0.0))
        if lexical <= 0 and semantic_score < .28: continue
        combined = min(1.0, lexical / 14.0) * .68 + semantic_score * .32
        match = SearchMatch(document.thread_id, combined, document.source_label,
            _excerpt(document.content, query))
        if document.thread_id not in best or match.score > best[document.thread_id].score:
            best[document.thread_id] = match
    return sorted(best.values(), key=lambda match: (-match.score, match.thread_id))
