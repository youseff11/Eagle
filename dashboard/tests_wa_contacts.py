"""A contact card or a place a client shares on WhatsApp reaches the chat as words.

Meta sends a shared contact as a *list* under ``contacts``; the hook read it as one block, raised, answered
500 and the card was never stored (19/10/2026, a client's "check above, I sent you her number").
"""

import json

from django.test import TestCase

from .models import AppSettings, InboundMessage


class SharedCardTests(TestCase):
    def setUp(self):
        conf = AppSettings.load()
        conf.whatsapp_phone_number_id = "111"
        conf.whatsapp_access_token = "token"
        conf.save()

    def post(self, message, wamid):
        payload = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "111"},
            "contacts": [{"wa_id": "201000000901", "profile": {"name": "Client"}}],
            "messages": [dict(message, **{"from": "201000000901", "id": wamid})],
        }}]}]}
        response = self.client.post("/webhooks/whatsapp/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        return InboundMessage.objects.get(external_id=wamid)

    def test_a_contact_card_is_stored_with_its_name_number_and_mail(self):
        row = self.post({"type": "contacts", "contacts": [{
            "name": {"formatted_name": "Karlijn Peters", "first_name": "Karlijn"},
            "org": {"company": "Linguix bv", "title": "OM"},
            "phones": [{"phone": "+31 6 1234 5678", "wa_id": "31612345678", "type": "CELL"}],
            "emails": [{"email": "karlijn@linguix.example", "type": "WORK"}],
        }]}, "wamid.card.1")
        self.assertEqual(row.body, "Karlijn Peters\nLinguix bv - OM\n+31 6 1234 5678\nkarlijn@linguix.example")

    def test_two_cards_are_kept_apart_and_a_number_with_no_text_falls_back_to_wa_id(self):
        row = self.post({"type": "contacts", "contacts": [
            {"name": {"first_name": "Abdes", "last_name": "El-Ajjouri"}, "phones": [{"wa_id": "32470000000"}]},
            {"name": {"formatted_name": "Karlijn"}, "phones": [{"phone": "+31 6 1"}]},
        ]}, "wamid.card.2")
        self.assertEqual(row.body, "Abdes El-Ajjouri\n32470000000\n\nKarlijn\n+31 6 1")

    def test_an_empty_or_odd_card_still_lands(self):
        self.assertEqual(self.post({"type": "contacts", "contacts": []}, "wamid.card.3").body, "[contacts]")
        self.assertEqual(self.post({"type": "contacts", "contacts": ["x", 5]}, "wamid.card.4").body, "[contacts]")
        self.assertEqual(self.post({"type": "reaction", "reaction": ["odd"]}, "wamid.card.5").body, "[reaction]")

    def test_a_shared_place_keeps_its_map_link(self):
        row = self.post({"type": "location", "location": {
            "latitude": 30.0444, "longitude": 31.2357, "name": "Office", "address": "Tahrir, Cairo",
        }}, "wamid.place.1")
        self.assertEqual(row.body, "Office\nTahrir, Cairo\nhttps://maps.google.com/?q=30.0444,31.2357")
        self.assertEqual(self.post({"type": "location", "location": {}}, "wamid.place.2").body, "[location]")
