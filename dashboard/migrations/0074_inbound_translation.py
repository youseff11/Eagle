from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0073_client_blocked'),
    ]

    operations = [
        migrations.AddField(
            model_name='inboundmessage',
            name='translation_ar',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='appsettings',
            name='chat_translate_enabled',
            field=models.BooleanField(default=False),
        ),
    ]
