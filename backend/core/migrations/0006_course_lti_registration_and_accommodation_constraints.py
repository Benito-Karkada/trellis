from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0005_questioncooldown")]

    operations = [
        migrations.AddField(
            model_name="ltiregistration",
            name="key_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="course",
            name="lti_registration",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="core.ltiregistration"),
        ),
        migrations.AddConstraint(
            model_name="accommodation",
            constraint=models.UniqueConstraint(fields=("membership", "activity"), name="unique_activity_accommodation"),
        ),
        migrations.AddConstraint(
            model_name="accommodation",
            constraint=models.UniqueConstraint(condition=models.Q(("activity__isnull", True)), fields=("membership",), name="unique_course_accommodation"),
        ),
    ]
