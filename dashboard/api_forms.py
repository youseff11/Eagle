"""A Django form as JSON, and JSON as a Django form's input.

The admin panel's forms (a person's file, a client's identity, the settings) have dozens of fields and many rules. The
new app does not copy those rules: it asks the same form what its fields are (``describe``), sends the values back as the
form's own input (``form_data``) and shows the form's own errors (``errors_of``). A rule added to the form later is a rule
here, with nothing to keep in step.

Two promises that matter more than the rest:

* A secret is never in an answer. A field drawn as a password (``PasswordInput``) is described with ``saved`` - whether
  there is a value - and never the value. Sent back: absent or empty keeps what is stored, a string replaces it, and an
  explicit ``null`` clears it. So a page that was opened, changed in one other box and saved cannot blank a token, and no
  GET can be turned into a way to read one.
* Only the form's own fields are accepted. A name the form does not have is refused, not ignored, so a typo does not look
  like a save that worked.
"""

import datetime
from decimal import Decimal

from django import forms
from django.db.models import QuerySet
from django.http import JsonResponse

#: The largest text a single field may carry in a request: far above any real value, below a body that wastes memory.
MAX_TEXT = 20_000
#: The most items a multiple choice may carry.
MAX_ITEMS = 500


class BadValues(ValueError):
    """The request's values are not shaped like this form's input. ``code`` names why; ``field`` names where."""

    def __init__(self, code, field=""):
        super().__init__(f"{code}: {field}")
        self.code = code
        self.field = field


# ---------------------------------------------------------------------------
# The form as JSON
# ---------------------------------------------------------------------------

def kind_of(field, secret=False):
    """How a front end draws this field: checkbox, multi, select, password, number, email, time, textarea or text.

    ``secret`` marks a field that holds a secret although its widget is a plain box (a verify token, a shared secret): it is
    drawn, described and read back as a password.
    """
    widget = field.widget
    if secret:
        return "password"
    if isinstance(field, forms.BooleanField):
        return "checkbox"
    if isinstance(field, (forms.MultipleChoiceField, forms.ModelMultipleChoiceField)):
        return "multi"
    if isinstance(field, (forms.ChoiceField, forms.ModelChoiceField)):
        return "select"
    if isinstance(widget, forms.PasswordInput):
        return "password"
    if isinstance(field, (forms.IntegerField, forms.DecimalField, forms.FloatField)):
        return "number"
    if isinstance(field, forms.EmailField):
        return "email"
    if isinstance(field, forms.TimeField):
        return "time"
    if isinstance(widget, forms.Textarea):
        return "textarea"
    return "text"


def is_secret(field):
    return kind_of(field) == "password"


def _scalar(value):
    """One value as JSON: strings for everything a text box holds (a decimal keeps its digits), booleans and ints as they are."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M")
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if hasattr(value, "pk"):
        return str(value.pk)
    return str(value)


def _plain(value):
    if isinstance(value, (list, tuple, set, frozenset, QuerySet)):
        return [str(_scalar(item)) for item in value]
    return _scalar(value)


def _choices(field):
    out = []
    for value, label in field.choices:
        out.append({"value": str(_scalar(value)), "label": str(label)})
    return out


def describe(form, secrets=()):
    """The fields of an unbound ``form`` as a list a front end can draw, with the values the form starts from.

    A bound form is refused: its values are what somebody typed, and a secret typed once must not be handed back.
    ``secrets`` names fields to treat as secrets besides the password boxes.
    """
    if form.is_bound:
        raise ValueError("describe() draws a form that has not been filled in")
    out = []
    for name, field in form.fields.items():
        kind = kind_of(field, name in secrets)
        widget_attrs = {**field.widget_attrs(field.widget), **field.widget.attrs}
        entry = {
            "name": name,
            "label": str(field.label or name),
            "kind": kind,
            "required": bool(field.required),
            "help": str(field.help_text or ""),
            "disabled": bool(field.disabled),
            "ltr": widget_attrs.get("dir") == "ltr",
        }
        for key in ("maxlength", "min", "max", "step", "rows", "placeholder"):
            if key in widget_attrs:
                entry[key] = widget_attrs[key]
        current = form[name].value()
        if kind == "password":
            # Whether there is one, never what it is.
            entry["saved"] = bool(current)
        else:
            entry["value"] = _plain(current)
        if kind in ("select", "multi"):
            entry["choices"] = _choices(field)
        out.append(entry)
    return out


def errors_of(form):
    """``{field: [messages]}`` for a form that did not validate; ``__all__`` holds the ones that belong to no field."""
    return {name: [str(message) for message in messages] for name, messages in form.errors.items()}


# ---------------------------------------------------------------------------
# JSON as the form's input
# ---------------------------------------------------------------------------

def _initial_input(form, name):
    """What the form would post for ``name`` if it were left alone: how an omitted field keeps its stored value."""
    value = form[name].value()
    field = form.fields[name]
    kind = kind_of(field)
    if kind == "checkbox":
        return bool(value)
    if kind == "multi":
        return [str(_scalar(item)) for item in (value or [])]
    return str(_scalar(value)) if value is not None else ""


def form_data(form_class, values, *, instance=None, form_kwargs=None, secrets=()):
    """The input to give ``form_class`` for these ``values``: the stored ones, with the sent ones laid over them.

    Raises :class:`BadValues` for a name the form does not have or a value of the wrong shape. A secret that is absent or
    empty keeps what is stored; ``None`` clears it (see the module note).
    """
    if not isinstance(values, dict):
        raise BadValues("bad_values")
    kwargs = dict(form_kwargs or {})
    if instance is not None:
        kwargs["instance"] = instance
    base = form_class(**kwargs)
    unknown = [name for name in values if name not in base.fields]
    if unknown:
        raise BadValues("unknown_field", str(unknown[0])[:60])
    data = {}
    for name, field in base.fields.items():
        kind = kind_of(field, name in secrets)
        data[name] = _initial_input(base, name)
        if name not in values:
            continue
        sent = values[name]
        if kind == "checkbox":
            if not isinstance(sent, bool):
                raise BadValues("bad_value", name)
            data[name] = sent
        elif kind == "multi":
            if not isinstance(sent, list) or len(sent) > MAX_ITEMS or any(
                isinstance(item, bool) or not isinstance(item, (str, int)) for item in sent
            ):
                raise BadValues("bad_value", name)
            data[name] = [str(item) for item in sent]
        elif kind == "password":
            if sent is None:
                data[name] = ""
            elif not isinstance(sent, str):
                raise BadValues("bad_value", name)
            elif sent != "":
                data[name] = sent
        else:
            if sent is None:
                data[name] = ""
            elif isinstance(sent, bool) or not isinstance(sent, (str, int, float)):
                raise BadValues("bad_value", name)
            else:
                data[name] = str(sent)
        text = data[name]
        if isinstance(text, str) and (len(text) > MAX_TEXT or "\x00" in text):
            raise BadValues("bad_value", name)
    return data


def invalid(form):
    """The answer for a form that did not validate: ``400 invalid`` with the form's own messages. Nothing was saved."""
    return JsonResponse({"ok": False, "error": "invalid", "errors": errors_of(form)}, status=400)


def filled(request, form_class, instance=None):
    """``(form, None)`` for a form filled in from the request's ``values`` and valid, else ``(None, the answer to give)``."""
    from .api_v1 import BadBody, _error, _object

    try:
        data = form_data(form_class, _object(request).get("values", {}), instance=instance)
    except (BadBody, BadValues):
        return None, _error(400, "bad_body")
    form = form_class(data, instance=instance) if instance is not None else form_class(data)
    if not form.is_valid():
        return None, invalid(form)
    return form, None
