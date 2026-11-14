from django.db import migrations, models
import django.db.models.deletion


def enable_pgvector(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.execute(
            "CREATE INDEX discussion_search_vector_idx "
            "ON core_discussionsearchdocument USING hnsw "
            "((embedding::vector(192)) vector_cosine_ops)"
        )


def disable_pgvector_index(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("DROP INDEX IF EXISTS discussion_search_vector_idx")


class Migration(migrations.Migration):
    dependencies = [("core", "0022_discussiondraft_editor_mode_and_more")]

    operations = [
        migrations.CreateModel(
            name="DiscussionSearchDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("content_type", models.CharField(choices=[("post", "Post"), ("answer", "Answer"), ("followup", "Followup")], max_length=12)),
                ("object_id", models.PositiveBigIntegerField()),
                ("source_label", models.CharField(max_length=40)),
                ("content", models.TextField(max_length=20200)),
                ("embedding", models.TextField()),
                ("content_hash", models.CharField(max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="discussion_search_documents", to="core.course")),
                ("thread", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="search_documents", to="core.discussionthread")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["course", "thread"], name="discussion_search_course_idx"),
                    models.Index(fields=["content_type", "object_id"], name="discussion_search_object_idx"),
                ],
                "constraints": [models.UniqueConstraint(fields=("thread", "content_type", "object_id"), name="unique_discussion_search_document")],
            },
        ),
        migrations.RunPython(enable_pgvector, disable_pgvector_index),
    ]
