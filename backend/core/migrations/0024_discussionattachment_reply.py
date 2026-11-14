from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0023_discussionsearchdocument")]

    operations = [
        migrations.AddField(
            model_name="discussionattachment",
            name="reply",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="attachments", to="core.discussionreply"),
        ),
    ]
