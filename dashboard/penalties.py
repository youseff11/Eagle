"""What happens to a star penalty after it is written: HR and the admin see it, then apply it or let it go.

The stars come off the moment the penalty is written (``User.apply_penalty``): the assignment order reads them, and a miss that
took nothing off until somebody noticed would be a miss with no consequence. What a person at HR or the admin decides is whether
the penalty *stands*. Applying it only marks it (the stars are already gone); forgiving it gives the stars back, up to the
company's maximum, and says so to the employee. HR decides a penalty once; the admin (the owner) may change what was decided -
forgive what was applied, apply again what was forgiven - and the stars follow.

Both writes leave an audit row, and the employee is told either way - a penalty that changes after they read it must not change
behind their back.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import services
from .models import AppSettings, RatingEvent, Role, User

#: What the door's action word means.
ACTIONS = {
    "confirm": RatingEvent.Decision.CONFIRMED,
    "forgive": RatingEvent.Decision.FORGIVEN,
}
MAX_NOTE = 200


def may_decide(user):
    """HR and the admin: the two the penalty is put in front of."""
    return bool(user and user.is_authenticated and user.is_active and (user.is_admin_role or user.role == Role.HR))


def may_change(user):
    """The admin alone: a decision HR or the admin took is his to take back."""
    return bool(user and user.is_authenticated and user.is_active and user.is_admin_role)


def announce(event):
    """Tell HR and the admin that stars came off somebody, with the amount and why, and where to decide."""
    person = event.user
    amount = abs(event.delta).normalize()
    for reviewer in User.objects.filter(role__in=(Role.HR, Role.ADMIN), is_active=True).exclude(pk=person.pk):
        services.notify(
            reviewer,
            title_ar="خصم نجوم من موظف",
            title_en="Stars taken off an employee",
            body_ar=f"{person.short_name}: {amount:f} نجمة - {event.reason_ar}. طبّق الخصم أو سامحه.",
            body_en=f"{person.short_name}: {amount:f} star(s) - {event.reason_en}. Apply it or forgive it.",
            level="warning", url=f"/hr/employees/{person.pk}/", task=event.task,
        )


def decide(event_pk, actor, action, note=""):
    """Apply or forgive one penalty. ``(event, "")`` on success, ``(None, error)`` when it is refused.

    Errors: ``forbidden`` (not HR or the admin), ``bad_action``, ``not_found``, ``own_record`` (HR deciding a penalty of their
    own - the admin may), ``decided`` (already decided, and either the actor is not the admin or it already stands as asked).
    """
    if not may_decide(actor):
        return None, "forbidden"
    if action not in ACTIONS:
        return None, "bad_action"
    with transaction.atomic():
        event = RatingEvent.objects.select_for_update().filter(pk=event_pk).select_related("user", "task").first()
        if event is None:
            return None, "not_found"
        person = User.objects.select_for_update().get(pk=event.user_id)
        if person.pk == actor.pk and not actor.is_admin_role:
            return None, "own_record"
        was = event.decision
        # Decided once, except by the admin, who may turn it round: what stands already is not decided again.
        if was != RatingEvent.Decision.PENDING and (not may_change(actor) or was == ACTIONS[action]):
            return None, "decided"
        # A raise is never made here: a penalty is a negative number, and the stars given back are what it took.
        amount = abs(event.delta)
        if action == "forgive":
            ceiling = AppSettings.load().max_rating
            person.rating = min(ceiling, person.rating + amount)
            person.save(update_fields=["rating"])
        elif was == RatingEvent.Decision.FORGIVEN:
            # Applied again: the stars that were given back come off again, never below nought.
            person.rating = max(Decimal("0.000"), person.rating - amount)
            person.save(update_fields=["rating"])
        event.decision = ACTIONS[action]
        event.decided_by = actor
        event.decided_at = timezone.now()
        event.decision_note = (note or "").strip()[:MAX_NOTE]
        event.save(update_fields=["decision", "decided_by", "decided_at", "decision_note"])
        services.log(
            actor, f"rating.{action}", person.username,
            f"{event.pk}: {event.delta}" + ("" if was == RatingEvent.Decision.PENDING else f" (was {was})"),
        )

    amount_text = f"{amount.normalize():f}"
    if action == "forgive":
        services.notify(
            person,
            title_ar="الخصم اتسامح",
            title_en="A penalty was forgiven",
            body_ar=f"رجعولك {amount_text} نجمة. السبب الأصلي: {event.reason_ar}",
            body_en=f"{amount_text} star(s) were given back. The original reason: {event.reason_en}",
            level="success",
        )
    else:
        services.notify(
            person,
            title_ar="الخصم اتطبق",
            title_en="A penalty was applied",
            body_ar=f"خصم {amount_text} نجمة اتأكد. السبب: {event.reason_ar}",
            body_en=f"The {amount_text} star(s) penalty stands. Reason: {event.reason_en}",
            level="danger",
        )
    return event, ""
