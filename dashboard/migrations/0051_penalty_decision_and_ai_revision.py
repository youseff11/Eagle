import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import dashboard.models


def old_penalties_stand(apps, schema_editor):
    """Every penalty written before this decision existed has stood for as long as it has been there: nothing for HR to chase."""
    apps.get_model("dashboard", "RatingEvent").objects.update(decision="confirmed")


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0050_notification_longer_body'),
    ]

    operations = [
        migrations.AddField(
            model_name='ratingevent',
            name='decision',
            field=models.CharField(
                choices=[('pending', 'Waiting for a decision'), ('confirmed', 'Applied'), ('forgiven', 'Forgiven')],
                default='pending', max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='ratingevent',
            name='decided_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='ratingevent',
            name='decided_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ratingevent',
            name='decision_note',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.RunPython(old_penalties_stand, migrations.RunPython.noop),
        migrations.CreateModel(
            name='AIRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('accepted', models.JSONField(blank=True, default=list)),
                (
                    'status',
                    models.CharField(
                        choices=[('running', 'Running'), ('done', 'Done'), ('error', 'Error')],
                        default='running', max_length=10,
                    ),
                ),
                ('file', models.FileField(blank=True, upload_to=dashboard.models.upload_revision)),
                ('original_name', models.CharField(blank=True, max_length=250)),
                ('size', models.BigIntegerField(default=0)),
                ('error_message', models.TextField(blank=True)),
                ('model_used', models.CharField(blank=True, max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'result',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name='revisions', to='dashboard.aicheckresult',
                    ),
                ),
                (
                    'requested_by',
                    models.ForeignKey(
                        null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={'ordering': ('-created_at', '-id')},
        ),
    ]
