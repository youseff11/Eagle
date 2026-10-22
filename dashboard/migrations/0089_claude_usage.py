"""The Claude card counts what the product spends instead of reading the bill: the account is an individual one and has no
Admin API key, so the key's column (0088) goes, and every call to Claude becomes a row of token counts and their price."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0088_usage_claude_key'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='appsettings',
            name='anthropic_admin_key',
        ),
        migrations.CreateModel(
            name='ClaudeUsage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('feature', models.CharField(max_length=20)),
                ('model', models.CharField(blank=True, max_length=80)),
                ('input_tokens', models.PositiveIntegerField(default=0)),
                ('output_tokens', models.PositiveIntegerField(default=0)),
                ('cache_write_tokens', models.PositiveIntegerField(default=0)),
                ('cache_read_tokens', models.PositiveIntegerField(default=0)),
                ('cost_usd', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
    ]
