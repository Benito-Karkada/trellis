from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0024_discussionattachment_reply')]

    operations = [
        migrations.CreateModel(
            name='AssignmentChecklist',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('student_view', models.BooleanField(default=False)),
                ('checked', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assignment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.lesson')),
                ('membership', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.membership')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('membership', 'assignment', 'student_view'),
                name='unique_assignment_checklist')]},
        ),
    ]
