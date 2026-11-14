"""Live PostgreSQL smoke check. Run through ``manage.py shell``."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client

from core.discussion_search import _postgres_cosine, embedding_provider
from core.models import Course, DiscussionSearchDocument, Membership


title = "__trellis_discussion_search_smoke__"
Course.objects.filter(title=title).delete()
get_user_model().objects.filter(username="__discussion_search_smoke__").delete()
user = get_user_model().objects.create_user("__discussion_search_smoke__")
course = Course.objects.create(title=title, term="Local smoke")
Membership.objects.create(course=course, user=user, role="student")
client = Client()
client.force_login(user)
course_header = {"HTTP_X_TRELLIS_COURSE": str(course.pk)}

try:
    semantic_post = client.post("/api/discussions/new/", {
        "title": "Account access", "body": "Authentication credentials are rejected by the course site."
    }, content_type="application/json", **course_header)
    assert semantic_post.status_code == 201, semantic_post.content
    thread_id = semantic_post.json()["thread"]["id"]
    answer = client.post(f"/api/discussions/{thread_id}/answer/", {
        "kind": "student", "body": "Create the environment from requirements.toml before opening the notebook."
    }, content_type="application/json", **course_header)
    assert answer.status_code == 200, answer.content
    client.post("/api/discussions/new/", {
        "title": "List exercise", "body": "Use a loop to add all the numbers."
    }, content_type="application/json", **course_header)

    semantic = client.get("/api/discussions/?q=I+cannot+log+in+with+my+password", **course_header)
    assert semantic.status_code == 200, semantic.content
    assert semantic.json()["threads"][0]["id"] == thread_id, semantic.json()
    exact = client.get("/api/discussions/?q=requirements.toml", **course_header)
    assert exact.json()["threads"][0]["search_match"]["source"] == "Students’ answer", exact.json()

    documents = list(DiscussionSearchDocument.objects.filter(thread_id=thread_id))
    vector_scores = _postgres_cosine(documents, embedding_provider().embed("account password"))
    assert connection.vendor == "postgresql"
    assert len(vector_scores) == 2, vector_scores
    with connection.cursor() as cursor:
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        pgvector_version = cursor.fetchone()[0]
    print(f"discussion search smoke passed: thread={thread_id}, documents={len(documents)}, pgvector={pgvector_version}")
finally:
    course.delete()
    user.delete()
