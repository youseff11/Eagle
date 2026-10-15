"""The B2B rows marked «contacted» by a WhatsApp message Meta reported as not delivered, before that unmarked them by itself
(15/10/2026, ``b2b.unmark_failed``): put right once, on the deploy."""

from django.db import migrations


def unmark(apps, schema_editor):
    from dashboard import b2b

    Lead = apps.get_model("dashboard", "Lead")
    LeadActivity = apps.get_model("dashboard", "LeadActivity")
    OutboundMessage = apps.get_model("dashboard", "OutboundMessage")
    failed = (
        LeadActivity.objects.filter(incoming=False, outbound__status="failed", outbound__channel="whatsapp")
        .values_list("outbound_id", flat=True).distinct()
    )
    b2b.unmark_failed(list(failed), models=(Lead, LeadActivity, OutboundMessage), log=False)


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0074_inbound_translation")]

    operations = [migrations.RunPython(unmark, migrations.RunPython.noop)]
