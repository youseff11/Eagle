import dashboard.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0089_claude_usage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='clientrequirement',
            name='text',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='clientrequirement',
            name='file',
            field=models.FileField(blank=True, upload_to=dashboard.models.upload_requirement_file),
        ),
        migrations.AddField(
            model_name='clientrequirement',
            name='original_name',
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AddField(
            model_name='clientrequirement',
            name='raw_name',
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AddField(
            model_name='clientrequirement',
            name='size',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='clientrequirement',
            name='mime',
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
