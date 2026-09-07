"""Create a ready-to-play demo dataset: users, shifts, clients, tasks, chats."""

from datetime import time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from dashboard import services
from dashboard.models import (
    AppSettings,
    Client,
    ClientRequirement,
    InboundMessage,
    Role,
    Shift,
    Task,
    User,
)

PASSWORD = "eagle1234"


class Command(BaseCommand):
    help = "Seed demo users, clients, messages and tasks for Eagle phase 1."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete demo rows first.")

    def handle(self, *args, **options):
        conf = AppSettings.load()

        if options["reset"]:
            # Task.client is PROTECT, so tasks and messages go first.
            Task.objects.all().delete()
            InboundMessage.objects.all().delete()
            Client.objects.all().delete()
            User.objects.exclude(is_superuser=True).delete()
            self.stdout.write(self.style.WARNING("Demo data cleared."))

        admin = self._user("admin", "Eagle", "Admin", Role.ADMIN, superuser=True)
        ops = self._user("operation", "Nour", "Operation", Role.OPERATION)
        ops2 = self._user("operation2", "Hana", "Operation", Role.OPERATION)

        lead_a = self._user("lead_ahmed", "Ahmed", "Fathy", Role.TEAM_LEAD, languages="EN, AR")
        lead_b = self._user("lead_mona", "Mona", "Saleh", Role.TEAM_LEAD, languages="FR, AR")

        translators = [
            self._user("tr_omar", "Omar", "Hassan", Role.TRANSLATOR, lead=lead_a, languages="EN>AR"),
            self._user("tr_sara", "Sara", "Adel", Role.TRANSLATOR, lead=lead_a, languages="AR>EN"),
            self._user("tr_kareem", "Kareem", "Nabil", Role.TRANSLATOR, lead=lead_b, languages="FR>AR"),
            self._user("tr_laila", "Laila", "Samir", Role.TRANSLATOR, lead=lead_b, languages="EN>FR"),
        ]

        # Round-the-clock shifts so everybody shows up as online while testing.
        for person in [ops, ops2, lead_a, lead_b] + translators:
            if not person.shifts.exists():
                for weekday in range(7):
                    Shift.objects.create(
                        user=person, weekday=weekday,
                        start_time=time(0, 0), end_time=time(23, 59),
                    )
        # One translator is deliberately offline to show the presence UI.
        translators[3].force_offline = True
        translators[3].save(update_fields=["force_offline"])

        clients = []
        for name, company, phone, email in [
            ("Mahmoud Ali", "Delta Pharma", "+201001112233", "mahmoud@delta.example"),
            ("Sherine Fouad", "Nile Legal", "+201225556677", "sherine@nilelegal.example"),
            ("John Carter", "Carter & Sons", "+447700900123", "john@carter.example"),
        ]:
            client, _ = Client.objects.get_or_create(
                phone=phone, defaults={"name": name, "company": company, "email": email}
            )
            clients.append(client)

        if not clients[0].requirements.exists():
            ClientRequirement.objects.create(
                client=clients[0], kind=ClientRequirement.Kind.DISLIKE,
                text="مش بيحب خط Calibri — يفضل Times New Roman 12.", author=ops,
            )
            ClientRequirement.objects.create(
                client=clients[0], kind=ClientRequirement.Kind.LIKE,
                text="بيحب تسليم PDF + Word مع بعض.", author=lead_a,
            )
            ClientRequirement.objects.create(
                client=clients[1], kind=ClientRequirement.Kind.RULE,
                text="Legal terminology must follow the client's glossary. No blue headings.",
                author=admin,
            )

        # Inbound messages, including one that must stay hidden from operation.
        services.ingest_message(
            channel="whatsapp", sender_identity=clients[0].phone,
            body="مساء الخير، محتاج ترجمة 12 صفحة عقد من عربي لإنجليزي بكرة الصبح.",
            external_id="demo-wa-1",
        )
        services.ingest_message(
            channel="email", sender_identity=clients[1].email,
            subject="Translation request - 4 files",
            body="Please translate the attached four affidavits to English by Thursday.",
            external_id="demo-mail-1",
        )
        services.ingest_message(
            channel="whatsapp", sender_identity=clients[2].phone,
            body="Hi, what is your rate per 1000 words?",
            external_id="demo-wa-rate",
        )

        # A live task sitting on the operation desk.
        task = services.create_task(
            client=clients[0], title="عقد شراكة — 12 صفحة", created_by=ops,
            description="ترجمة عقد من العربي للإنجليزي، تسليم Word + PDF.",
            source_lang="AR", target_lang="EN", priority="high",
            deadline=timezone.now() + timedelta(hours=6),
        )

        # A second task already flowing to show every screen populated.
        task2 = services.create_task(
            client=clients[1], title="Affidavits pack (4 files)", created_by=ops2,
            description="Legal affidavits, glossary attached.",
            source_lang="AR", target_lang="EN", priority="normal",
            deadline=timezone.now() + timedelta(days=1),
        )
        a1 = services.assign_to_lead(task2, lead_a, ops2)
        services.accept_assignment(a1, lead_a)
        a2 = services.assign_to_translator(task2, translators[0], lead_a)
        services.accept_assignment(a2, translators[0])

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write("")
        self.stdout.write(f"  admin        / {PASSWORD}   (Admin)")
        self.stdout.write(f"  operation    / {PASSWORD}   (Operation)")
        self.stdout.write(f"  lead_ahmed   / {PASSWORD}   (Team leader)")
        self.stdout.write(f"  tr_omar      / {PASSWORD}   (Translator)")
        self.stdout.write("")
        self.stdout.write(f"Open tasks: {task.code}, {task2.code}")
        self.stdout.write(f"Response window: {conf.response_window_seconds}s")

    # ------------------------------------------------------------------
    def _user(self, username, first, last, role, lead=None, languages="", superuser=False):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": first, "last_name": last, "role": role,
                "languages": languages, "team_lead": lead,
                "is_staff": superuser, "is_superuser": superuser,
                "email": f"{username}@eagle.example",
            },
        )
        if created:
            user.set_password(PASSWORD)
            user.save()
        else:
            changed = False
            if user.role != role:
                user.role, changed = role, True
            if lead and user.team_lead_id != lead.id:
                user.team_lead, changed = lead, True
            if changed:
                user.save(update_fields=["role", "team_lead"])
        return user
