from django.db import migrations


def owner_has_no_attendance(apps, schema_editor):
    """The owner (every admin) does not clock in: the flag is switched off for the ones that already exist."""
    User = apps.get_model("dashboard", "User")
    User.objects.filter(role="admin").update(attendance_enabled=False)
    User.objects.filter(is_superuser=True).update(attendance_enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0043_user_avatar"),
    ]

    operations = [
        migrations.RunPython(owner_has_no_attendance, migrations.RunPython.noop),
    ]
