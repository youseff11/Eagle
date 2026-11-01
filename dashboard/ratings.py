"""The stars start again every month, and the months that are over are kept.

``User.rating`` is this month's stars. The first time anything touches a person in a new month (a penalty, the worker's sweep,
a file being opened) ``roll_user`` writes the month that ended into ``RatingMonth`` and gives the person the company maximum
again. Nothing depends on the worker being up: whoever reads first does the roll, and it can run twice without harm.

A person who has never been rolled (``rating_month`` null, every account from before this existed) is stamped with the current
month and keeps the stars they have: nobody's stars are wiped the day this ships.

A penalty is decided days after it is written, sometimes in the next month. Forgiving or applying again then moves the month
the penalty belongs to (``adjust``), never the current month's stars.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import AppSettings, RatingMonth, Role, User


def this_month(now=None):
    """First day of the month in Cairo time."""
    day = timezone.localdate(now) if now is not None else timezone.localdate()
    return day.replace(day=1)


def roll_user(person, now=None, ceiling=None):
    """Close the month ``person`` is still on, if it is over, and start the new one. True when a month was closed."""
    current = this_month(now)
    old = person.rating_month
    if old is not None and old >= current:
        return False
    if old is None:
        User.objects.filter(pk=person.pk, rating_month__isnull=True).update(rating_month=current)
        person.rating_month = current
        return False
    ceiling = ceiling if ceiling is not None else AppSettings.load().max_rating
    with transaction.atomic():
        # Compare and set: two requests rolling the same person at once close the month once.
        won = User.objects.filter(pk=person.pk, rating_month=old).update(rating=ceiling, rating_month=current)
        if won:
            closing = Decimal(person.rating)
            if person.role == Role.TRANSLATOR or closing != ceiling:
                RatingMonth.objects.get_or_create(
                    user_id=person.pk, month=old, defaults={"closing": closing, "opening": ceiling},
                )
    person.rating = ceiling
    person.rating_month = current
    return bool(won)


def roll(now=None):
    """Roll everybody whose stars belong to a month that is over. Returns how many months were closed."""
    current = this_month(now)
    ceiling = AppSettings.load().max_rating
    closed = 0
    for person in User.objects.filter(rating_month__lt=current) | User.objects.filter(rating_month__isnull=True):
        if roll_user(person, now, ceiling):
            closed += 1
    return closed


def adjust(person, event, amount, give):
    """Move the stars of the month ``event`` belongs to: ``give`` adds ``amount`` (up to the maximum), else it takes it off.

    This month's penalty moves ``person.rating`` (the caller saves it); an older month's moves its history row instead.
    """
    ceiling = AppSettings.load().max_rating
    month = event.created_at
    month = timezone.localtime(month).date().replace(day=1)
    if person.rating_month is None or month >= person.rating_month:
        person.rating = min(ceiling, person.rating + amount) if give else max(Decimal("0.000"), person.rating - amount)
        return True
    row = RatingMonth.objects.select_for_update().filter(user_id=person.pk, month=month).first()
    if row is None:
        return False
    row.closing = min(ceiling, row.closing + amount) if give else max(Decimal("0.000"), row.closing - amount)
    row.save(update_fields=["closing"])
    return False


def history(person, limit=24):
    """The closed months, newest first, as the file shows them."""
    return [
        {"month": row.month.strftime("%Y-%m"), "closing": f"{row.closing.normalize():f}", "opening": f"{row.opening.normalize():f}"}
        for row in person.rating_months.all()[:limit]
    ]
