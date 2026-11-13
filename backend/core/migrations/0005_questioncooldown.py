from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_activity_metadata_lesson_source_path_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='QuestionCooldown',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question_id', models.CharField(max_length=64)),
                ('locked_until', models.DateTimeField()),
                ('membership', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.membership')),
                ('revision', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.revision')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('membership', 'revision', 'question_id'), name='unique_question_cooldown')],
            },
        ),
    ]
