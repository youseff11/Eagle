"""Count a job's words out of its files instead of asking someone to type them.

The source count is what payroll uses. The translated count is stored beside it
so the gap between them can be looked at - that gap is the only cheap signal
that a translation is unfinished or padded.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0008_payroll"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="source_words",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="task",
            name="translated_words",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="task",
            name="source_word_method",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="task",
            name="translated_word_method",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="task",
            name="word_count_state",
            field=models.CharField(
                choices=[
                    ("empty", "Not counted yet"),
                    ("auto", "Counted from the files"),
                    ("review", "Needs a human to confirm"),
                    ("manual_needed", "Must be entered by hand"),
                    ("confirmed", "Confirmed by a person"),
                ],
                db_index=True, default="empty", max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="word_count_note",
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AddField(
            model_name="payrollsettings",
            name="word_count_gap_percent",
            field=models.PositiveSmallIntegerField(
                default=40,
                help_text=(
                    "Above this gap between source and translation, a person "
                    "confirms the count."
                ),
            ),
        ),
    ]
