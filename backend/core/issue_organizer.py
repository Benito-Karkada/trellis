"""Teacher-facing clustering of repeated student discussion issues."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .discussion_search import cosine, embedding_provider
from .models import DiscussionThread


SIMILARITY_THRESHOLD = .34
IMPACT_WORDS = re.compile(
    r"\b(blocked|blocking|cannot|can't|crash|deadline|due|error|fail|failed|grade|"
    r"login|missing|not working|submit|submission|unable|urgent)\b", re.I)


@dataclass
class Candidate:
    thread: DiscussionThread
    text: str
    vector: list[float]
    student_ids: set[int]
    open: bool


@dataclass
class Cluster:
    candidates: list[Candidate] = field(default_factory=list)
    centroid: list[float] = field(default_factory=list)

    def add(self, candidate: Candidate) -> None:
        self.candidates.append(candidate)
        dimensions = len(candidate.vector)
        totals = [sum(item.vector[index] for item in self.candidates) for index in range(dimensions)]
        norm = math.sqrt(sum(value * value for value in totals))
        self.centroid = [value / norm for value in totals] if norm else totals


def _candidate(thread: DiscussionThread) -> Candidate | None:
    student_ids: set[int] = set()
    text = [thread.title]
    if thread.author and thread.author.role == "student":
        student_ids.add(thread.author_id)
        text.append(thread.body)
    roots_open = False
    for reply in thread.replies.all():
        if reply.deleted_at is not None:
            continue
        if reply.parent_id is None and not reply.resolved:
            roots_open = True
        if reply.author and reply.author.role == "student":
            student_ids.add(reply.author_id)
            text.append(reply.body)
    if not student_ids:
        return None
    content = "\n".join(text)
    answered = any(answer.kind == "instructor" for answer in thread.answers.all())
    return Candidate(thread, content, embedding_provider().embed(content), student_ids,
        open=not answered or roots_open)


def _representative(cluster: Cluster) -> Candidate:
    return max(cluster.candidates, key=lambda item: sum(
        cosine(item.vector, other.vector) for other in cluster.candidates))


def _priority(cluster: Cluster, students: int, open_count: int) -> str:
    reports = len(cluster.candidates)
    has_impact = bool(IMPACT_WORDS.search(" ".join(item.text for item in cluster.candidates)))
    score = reports * 2 + min(students, 8) + open_count * 1.5 + (2 if has_impact else 0)
    if reports >= 4 or students >= 5:
        return "high"
    if reports >= 3 or students >= 3 or score >= 9:
        return "medium"
    return "low"


def organize_course_issues(course) -> list[dict]:
    threads = DiscussionThread.objects.filter(course=course, kind="question", deleted_at=None).select_related(
        "author__user").prefetch_related("folders", "answers", "replies__author__user")
    candidates = [item for thread in threads if (item := _candidate(thread))]
    clusters: list[Cluster] = []
    for candidate in sorted(candidates, key=lambda item: item.thread.pk):
        matches = [(cosine(candidate.vector, cluster.centroid), cluster) for cluster in clusters]
        similarity, cluster = max(matches, default=(-1.0, None), key=lambda item: item[0])
        if cluster is None or similarity < SIMILARITY_THRESHOLD:
            cluster = Cluster()
            clusters.append(cluster)
        cluster.add(candidate)

    issues = []
    for cluster in clusters:
        student_ids = set().union(*(item.student_ids for item in cluster.candidates))
        reports = len(cluster.candidates)
        if reports < 2 and len(student_ids) < 3:
            continue
        representative = _representative(cluster)
        open_count = sum(item.open for item in cluster.candidates)
        priority = _priority(cluster, len(student_ids), open_count)
        posts = sorted(cluster.candidates, key=lambda item: (-item.open, -item.thread.updated_at.timestamp()))
        issues.append({
            "id": min(item.thread.pk for item in cluster.candidates),
            "title": representative.thread.title,
            "summary": " ".join(representative.thread.body.split())[:220],
            "priority": priority,
            "student_count": len(student_ids),
            "post_count": reports,
            "open_count": open_count,
            "posts": [{
                "id": item.thread.pk,
                "title": item.thread.title,
                "visibility": item.thread.visibility,
                "created_at": item.thread.created_at.isoformat(),
                "open": item.open,
                "folders": [folder.name for folder in item.thread.folders.all()],
            } for item in posts],
        })
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(issues, key=lambda issue: (order[issue["priority"]], -issue["student_count"],
        -issue["post_count"], issue["title"].lower()))
