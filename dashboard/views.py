"""Page views for the Eagle dashboard."""

from django.contrib import messages as flash
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import payroll, services, wordcount
from .forms import (
    AICheckForm,
    ClientForm,
    PayrollSettingsForm,
    ProductionTierForm,
    RequirementForm,
    SalaryRecordForm,
    SettingsForm,
    ShiftForm,
    SimulateMessageForm,
    StaffCreateForm,
    StaffEditForm,
    TaskForm,
    ViolationForm,
    WorkDayForm,
)
from .models import (
    ACTIVE_TASK_STATUSES,
    LEAVE_STATUSES,
    ApprovalStatus,
    AppSettings,
    AssignmentStatus,
    ChatAttachment,
    ChatRoom,
    Client,
    InboundMessage,
    Notification,
    PayrollLine,
    PayrollPeriod,
    PayrollSettings,
    ProductionTier,
    Role,
    RoomKind,
    Shift,
    Task,
    TaskStatus,
    TierScale,
    User,
    Violation,
    WordCountState,
    WorkDay,
)
from .permissions import admin_only, role_required


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.get_user())
        nxt = request.POST.get("next") or request.GET.get("next") or ""
        if nxt and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(nxt)
        return redirect("dashboard:home")

    form.fields["username"].widget.attrs.update({
        "class": "input", "dir": "ltr", "autocomplete": "username",
        "autofocus": True, "placeholder": "username",
    })
    form.fields["password"].widget.attrs.update({
        "class": "input", "dir": "ltr", "autocomplete": "current-password",
        "placeholder": "••••••••",
    })
    return render(request, "auth/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    auth_logout(request)
    return redirect("dashboard:login")


@login_required
def home(request):
    user = request.user
    if user.is_admin_role:
        return redirect("dashboard:admin_overview")
    if user.is_operation:
        return redirect("dashboard:ops_inbox")
    if user.is_team_lead:
        return redirect("dashboard:lead_home")
    return redirect("dashboard:translator_home")


# ---------------------------------------------------------------------------
# Public legal pages
#
# These are open to everyone — no login. Meta requires a reachable privacy
# policy and data-deletion page before a WhatsApp app can be published, and
# the pages carry the registered legal name for business verification.
# ---------------------------------------------------------------------------

def privacy(request):
    return render(request, "public/privacy.html", {"page": "privacy"})


def terms(request):
    return render(request, "public/terms.html", {"page": "terms"})


def data_deletion(request):
    return render(request, "public/data_deletion.html", {"page": "deletion"})


# ---------------------------------------------------------------------------
# Operation
# ---------------------------------------------------------------------------

@role_required(Role.OPERATION)
def ops_inbox(request):
    user = request.user
    state = request.GET.get("state", "")
    query = request.GET.get("q", "").strip()
    messages_list = list(services.inbox_queryset(user, state, query)[:150])

    context = {
        "messages_list": messages_list,
        # The live feed asks for anything newer than this.
        "last_message_id": messages_list[0].id if messages_list else 0,
        "state": state,
        "query": query,
        "unclaimed_count": InboundMessage.objects.filter(
            claimed_by__isnull=True, is_rate_blocked=False
        ).count(),
        "blocked_count": InboundMessage.objects.filter(is_rate_blocked=True).count(),
    }
    return render(request, "ops/inbox.html", context)


def _chat_sidebar(user, query, kind):
    """The left-hand list: 1:1 client chats and groups, newest first."""
    rows = []
    # The 1:1 list is every client the business has ever talked to. Only the
    # roles that already own the client inbox may see it — a translator who is
    # in one group must not get a directory of every client and their words.
    sees_all_clients = user.is_operation or user.is_admin_role
    if kind in ("all", "chats") and sees_all_clients:
        for client in services.client_conversations(user, query)[:100]:
            preview = services.conversation_preview(client, user)
            rows.append({
                "is_group": False,
                "client": client,
                "code": client.code,
                "label": client.label_for(user),
                "url": f"/ops/chats/{client.code}/",
                "preview": preview,
            })
    if kind in ("all", "groups"):
        for room in services.groups_for(user, query)[:100]:
            client = room.relay_client
            rows.append({
                "is_group": True,
                "room": room,
                "client": client,
                "code": f"g{room.id}",
                "label": room.display_title,
                "url": f"/ops/chats/g/{room.id}/",
                "preview": services.group_preview(room, user),
            })
    rows.sort(key=lambda r: r["preview"]["at"] or timezone.now(), reverse=True)
    return rows


def _chats_context(request, kind):
    user = request.user
    query = request.GET.get("q", "").strip()
    may_create = AppSettings.load().can_create_group(user)
    context = {
        "conversations": _chat_sidebar(user, query, kind),
        "query": query,
        "filter": kind,
        "can_create_group": may_create,
        # Only the roles that see the whole client list get the filter — for
        # everyone else this page is their groups and nothing else.
        "show_filter": user.is_operation or user.is_admin_role,
        "group_clients": [],
        "group_people": [],
    }
    if may_create:
        context["group_clients"] = Client.objects.filter(is_active=True).order_by("code")[:300]
        context["group_people"] = (
            User.objects.filter(is_active=True).exclude(pk=user.pk)
            .order_by("role", "username")[:200]
        )
    return context


@login_required
def ops_chats(request, code=""):
    """WhatsApp-style conversations with the clients.

    Open to everyone, but not equally: the 1:1 client list is the whole client
    directory, so it stays with the roles that own the client inbox. A team
    leader or translator lands here on their own groups and nothing else —
    which is what they needed a way in for.
    """
    user = request.user
    sees_all_clients = user.is_operation or user.is_admin_role

    kind = request.GET.get("type", "all")
    if kind not in ("all", "chats", "groups"):
        kind = "all"
    if not sees_all_clients:
        kind = "groups"
    context = _chats_context(request, kind)

    active = None
    if code:
        # A 1:1 client conversation is not theirs to open.
        if not sees_all_clients:
            raise Http404
        active = get_object_or_404(Client, code=code)
    elif sees_all_clients:
        first = next((r for r in context["conversations"] if not r["is_group"]), None)
        active = first["client"] if first else None

    context.update({
        "active": active,
        "active_code": active.code if active else "",
        "thread": services.client_thread(active, user) if active else [],
        "channel": services.client_channel(active) if active else "",
        # On a phone the list and the conversation are two screens, like
        # WhatsApp. Only an explicitly chosen conversation opens the second
        # one; the bare /ops/chats/ URL is the list.
        "has_selection": bool(code),
    })
    return render(request, "ops/chats.html", context)


@login_required
def ops_group_chat(request, room_id):
    """One group's conversation, rendered by the same page as a 1:1 chat."""
    user = request.user
    room = get_object_or_404(
        ChatRoom.objects.select_related("client", "task"),
        pk=room_id, kind=RoomKind.CLIENT,
    )
    if not room.can_access(user):
        raise Http404
    if room.task_id and not room.task.can_view(user):
        raise Http404

    kind = request.GET.get("type", "all")
    if kind not in ("all", "chats", "groups"):
        kind = "all"
    if not (user.is_operation or user.is_admin_role):
        kind = "groups"
    context = _chats_context(request, kind)

    client = room.relay_client
    members = list(room.members.all())
    context.update({
        "active": client,
        "active_group": room,
        "active_code": f"g{room.id}",
        "thread": services.group_thread(room, user),
        "channel": services.client_channel(client) if client else "",
        "members": members,
        "can_add_members": AppSettings.load().can_create_group(user),
        "addable_people": User.objects.filter(is_active=True)
                              .exclude(pk__in=[m.pk for m in members])
                              .order_by("role", "username")[:200],
        "has_selection": True,
    })
    return render(request, "ops/chats.html", context)


@role_required(Role.OPERATION)
def ops_tasks(request):
    status = request.GET.get("status", "")
    qs = Task.objects.select_related("client", "team_lead", "translator")
    if status == "open":
        qs = qs.filter(status__in=ACTIVE_TASK_STATUSES)
    elif status:
        qs = qs.filter(status=status)
    return render(request, "ops/tasks.html", {
        "tasks": qs[:200],
        "status": status,
        "statuses": TaskStatus.choices,
        "counters": _task_counters(),
    })


def _task_counters():
    return {
        "new": Task.objects.filter(status=TaskStatus.NEW).count(),
        "open": Task.objects.filter(status__in=ACTIVE_TASK_STATUSES).count(),
        "review": Task.objects.filter(status=TaskStatus.UNDER_REVIEW).count(),
        "ready": Task.objects.filter(status=TaskStatus.REVIEWED).count(),
        "delivered": Task.objects.filter(status=TaskStatus.DELIVERED).count(),
    }


@role_required(Role.OPERATION)
def ops_task_new(request):
    message = None
    message_id = request.GET.get("message") or request.POST.get("message")
    if message_id:
        message = InboundMessage.objects.filter(pk=message_id).first()
        if message and message.is_rate_blocked and not request.user.is_admin_role:
            message = None

    initial = {}
    if message:
        initial = {
            "client": message.client_id,
            "title": (message.subject or message.body[:60] or "Translation request").strip(),
            "description": message.body,
        }

    form = TaskForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        task = services.create_task(
            client=form.cleaned_data["client"],
            title=form.cleaned_data["title"],
            created_by=request.user,
            description=form.cleaned_data["description"],
            deadline=form.cleaned_data["deadline"],
            priority=form.cleaned_data["priority"],
            source_lang=form.cleaned_data["source_lang"],
            target_lang=form.cleaned_data["target_lang"],
            messages=[message] if message else None,
        )
        if message and not message.claimed_by_id:
            services.claim_message(message, request.user)
        flash.success(request, f"{task.code}")
        return redirect("dashboard:task_detail", code=task.code)

    return render(request, "ops/task_form.html", {"form": form, "source_message": message})


@role_required(Role.OPERATION)
def ops_team(request):
    return render(request, "ops/team.html", {"rows": services.team_overview()})


# ---------------------------------------------------------------------------
# Team leader / translator home
# ---------------------------------------------------------------------------

@role_required(Role.TEAM_LEAD)
def lead_home(request):
    user = request.user
    tasks = Task.objects.filter(team_lead=user).select_related("client", "translator")
    team = User.objects.filter(team_lead=user, is_active=True).prefetch_related("shifts")
    return render(request, "lead/home.html", {
        "open_tasks": tasks.filter(status__in=ACTIVE_TASK_STATUSES),
        "done_tasks": tasks.filter(status__in=[TaskStatus.DELIVERED, TaskStatus.CANCELLED])[:20],
        "team": team,
        "free_count": sum(1 for m in team if m.is_online and not m.is_busy),
        "busy_count": sum(1 for m in team if m.is_online and m.is_busy),
        "offline_count": sum(1 for m in team if not m.is_online),
    })


@role_required(Role.TRANSLATOR)
def translator_home(request):
    user = request.user
    tasks = Task.objects.filter(translator=user).select_related("client", "team_lead")
    return render(request, "translator/home.html", {
        "open_tasks": tasks.filter(status__in=ACTIVE_TASK_STATUSES),
        "done_tasks": tasks.filter(status__in=[TaskStatus.DELIVERED, TaskStatus.CANCELLED])[:20],
        "rating_events": user.rating_events.all()[:10],
    })


# ---------------------------------------------------------------------------
# Task detail
# ---------------------------------------------------------------------------

@login_required
def task_detail(request, code):
    task = get_object_or_404(
        Task.objects.select_related("client", "team_lead", "translator", "created_by"),
        code=code,
    )
    user = request.user
    if not task.can_view(user):
        raise Http404

    # Tasks that were already running when the client room shipped never got
    # one. Backfill on first view — guarded by exists() so an ordinary GET
    # stays read-only once the room is there.
    if (
        task.status in ACTIVE_TASK_STATUSES
        and task.rooms.exists()
        and not task.rooms.filter(kind=RoomKind.CLIENT).exists()
    ):
        services.ensure_room(task, RoomKind.CLIENT)

    rooms = list(services.rooms_for(task, user))
    active_room = None
    room_id = request.GET.get("room")
    if room_id:
        active_room = next((r for r in rooms if str(r.id) == str(room_id)), None)
    if active_room is None and rooms:
        # Never land on the client room by default: opening the page should not
        # put a box that talks to the client under someone's cursor. The most
        # recent *internal* room wins, and the client tab is a deliberate click.
        # If the only room this person can see is the client one, show nothing
        # rather than opening a live line to the client under their cursor.
        internal = [r for r in rooms if r.kind != RoomKind.CLIENT]
        active_room = internal[-1] if internal else None

    pending = task.pending_assignment
    my_pending = pending if (pending and pending.assignee_id == user.id) else None

    leads = translators = []
    if user.is_operation or user.is_admin_role:
        leads = User.objects.filter(role=Role.TEAM_LEAD, is_active=True).prefetch_related("shifts")
    if user.is_team_lead or user.is_admin_role:
        base = User.objects.filter(role=Role.TRANSLATOR, is_active=True)
        if user.is_team_lead:
            base = base.filter(team_lead=user)
        elif task.team_lead_id:
            base = base.filter(team_lead_id=task.team_lead_id)
        translators = base.prefetch_related("shifts")

    # Newest 200, then back into reading order. A client room accumulates the
    # whole conversation, so an unbounded list would grow without limit.
    chat_messages = list(reversed(
        active_room.messages
        .select_related("sender", "inbound")
        .prefetch_related("attachments", "inbound__attachments")
        .order_by("-id")[:200]
    )) if active_room else []

    # Files the operation can forward to the client (translator's output first).
    deliverables = []
    if user.is_operation or user.is_admin_role:
        rows = (
            ChatAttachment.objects
            .filter(message__room__task=task)
            .select_related("message", "message__sender")
            .order_by("-id")[:40]
        )
        for attachment in rows:
            sender = attachment.message.sender
            deliverables.append({
                "id": attachment.id,
                "name": attachment.original_name or attachment.file.name.rsplit("/", 1)[-1],
                "size": attachment.pretty_size,
                "url": attachment.file.url,
                "sender": sender.short_name if sender else "—",
                # Default-check whatever the translator sent.
                "final": bool(task.translator_id and sender and sender.id == task.translator_id),
            })

    context = {
        "task": task,
        "rooms": rooms,
        "active_room": active_room,
        "chat_messages": chat_messages,
        "last_message_id": chat_messages[-1].id if chat_messages else 0,
        "pending": pending,
        "my_pending": my_pending,
        "leads": leads,
        "translators": translators,
        "requirements": task.client.requirements.select_related("author"),
        "requirement_form": RequirementForm(),
        "ai_form": AICheckForm(),
        "ai_checks": task.ai_checks.all()[:5],
        "history": task.assignments.select_related("assignee", "assigned_by")[:20],
        "deliverables": deliverables,
        "deliveries": task.deliveries.select_related("created_by")[:5],
        "client_channel": services.client_channel(task.client),
        "client_reachable": bool(task.client.phone or task.client.email),
        "source_messages": (
            task.source_messages.prefetch_related("attachments")
            if (user.is_operation or user.is_admin_role) else []
        ),
        "conf": AppSettings.load(),
        # Who may settle a disputed word count: the people who can see both
        # the client's file and the translator's, never the translator.
        "can_set_words": user.is_admin_role or user.is_operation
        or task.team_lead_id == user.id,
    }
    return render(request, "shared/task_detail.html", context)


@login_required
@require_POST
def task_word_count(request, code):
    """Recount from the files, or accept a number a person stands behind."""
    task = get_object_or_404(Task, code=code)
    user = request.user
    # The translator uploads the file their own bonus is measured from, so
    # they are the one role that cannot settle the number.
    if not (user.is_admin_role or user.is_operation or task.team_lead_id == user.id):
        raise Http404

    action = request.POST.get("action") or "recount"
    if action == "recount":
        wordcount.recount_task(task)
        services.log(user, "task.word_count.recount", task.code, str(task.word_count))
    elif action == "manual":
        raw = (request.POST.get("words") or "").strip()
        if not raw.isdigit():
            flash.error(request, "اكتب رقم صحيح.")
            return redirect("dashboard:task_detail", code=code)
        wordcount.confirm_task(task, user, words=int(raw))
    elif action in ("source", "translated"):
        wordcount.confirm_task(task, user, use=action)
    else:
        raise Http404

    flash.success(request, str(task.word_count))
    return redirect("dashboard:task_detail", code=code)


@login_required
@require_POST
def task_add_requirement(request, code):
    task = get_object_or_404(Task, code=code)
    user = request.user
    if not (user.is_admin_role or user.is_operation or task.team_lead_id == user.id):
        raise Http404
    form = RequirementForm(request.POST)
    if form.is_valid():
        req = form.save(commit=False)
        req.client = task.client
        req.author = user
        req.save()
        services.log(user, "client.requirement", task.client.code, req.text[:80])
    return redirect("dashboard:task_detail", code=code)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

@role_required(Role.OPERATION, Role.TEAM_LEAD)
def client_list(request):
    query = request.GET.get("q", "").strip()
    qs = Client.objects.all()
    if query:
        qs = qs.filter(Q(code__icontains=query) | Q(name__icontains=query))
    return render(request, "shared/clients.html", {"clients": qs[:200], "query": query})


@role_required(Role.OPERATION, Role.TEAM_LEAD)
def client_detail(request, code):
    client = get_object_or_404(Client, code=code)
    user = request.user
    if request.method == "POST":
        if user.is_translator:
            raise Http404
        form = RequirementForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.client = client
            req.author = user
            req.save()
            services.log(user, "client.requirement", client.code, req.text[:80])
            return redirect("dashboard:client_detail", code=code)
    else:
        form = RequirementForm()
    return render(request, "shared/client_detail.html", {
        "client": client,
        "form": form,
        "requirements": client.requirements.select_related("author"),
        "tasks": client.tasks.all()[:30],
    })


@admin_only
def client_form(request, code=None):
    client = get_object_or_404(Client, code=code) if code else None
    form = ClientForm(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        flash.success(request, obj.code)
        return redirect("dashboard:client_detail", code=obj.code)
    return render(request, "adminx/client_form.html", {"form": form, "client": client})


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@login_required
def notifications(request):
    items = request.user.notifications.all()[:100]
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return render(request, "shared/notifications.html", {"items": items})


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------

@admin_only
def admin_overview(request):
    now = timezone.now()
    return render(request, "adminx/overview.html", {
        "counters": _task_counters(),
        "clients": Client.objects.count(),
        "staff": User.objects.filter(is_active=True).count(),
        "blocked": InboundMessage.objects.filter(is_rate_blocked=True)[:20],
        "late_tasks": Task.objects.filter(
            status__in=ACTIVE_TASK_STATUSES, deadline__lt=now
        ).select_related("client", "translator")[:20],
        "recent_tasks": Task.objects.select_related("client")[:15],
        "pending": _pending_assignments(),
    })


def _pending_assignments():
    from .models import Assignment

    return Assignment.objects.filter(status=AssignmentStatus.PENDING).select_related(
        "task", "assignee"
    )[:20]


@admin_only
def admin_settings(request):
    conf = AppSettings.load()
    form = SettingsForm(request.POST or None, instance=conf)

    if request.method == "POST":
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        if form.is_valid():
            form.save()
            services.log(request.user, "settings.update")
            if is_ajax:
                # The "save & test" button saves first, then calls the test API.
                return JsonResponse({"ok": True})
            flash.success(request, "saved")
            return redirect("dashboard:admin_settings")
        if is_ajax:
            return JsonResponse(
                {"ok": False, "errors": {k: [str(e) for e in v] for k, v in form.errors.items()}},
                status=400,
            )

    host = request.get_host()
    return render(request, "adminx/settings.html", {
        "form": form,
        "conf": conf,
        "webhook_url": request.build_absolute_uri(reverse("dashboard:wh_whatsapp")),
        # Meta can only reach a public HTTPS address.
        "is_local": host.split(":")[0] in ("127.0.0.1", "localhost", "0.0.0.0")
        or host.startswith("192.168.") or host.startswith("10."),
        "is_https": request.is_secure(),
    })


@admin_only
def admin_users(request):
    return render(request, "adminx/users.html", {
        "users": User.objects.all().prefetch_related("shifts", "team_members"),
        "roles": Role.choices,
    })


@admin_only
def admin_user_new(request):
    form = StaffCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        services.log(request.user, "user.create", user.username)
        return redirect("dashboard:admin_user_edit", pk=user.pk)
    return render(request, "adminx/user_form.html", {"form": form, "obj": None})


@admin_only
def admin_user_edit(request, pk):
    obj = get_object_or_404(User, pk=pk)
    form = StaffEditForm(request.POST or None, instance=obj)
    shift_form = ShiftForm()
    if request.method == "POST" and form.is_valid():
        form.save()
        services.log(request.user, "user.update", obj.username)
        flash.success(request, "saved")
        return redirect("dashboard:admin_user_edit", pk=pk)
    return render(request, "adminx/user_form.html", {
        "form": form, "obj": obj, "shift_form": shift_form,
        "shifts": obj.shifts.all(), "events": obj.rating_events.all()[:20],
    })


@admin_only
@require_POST
def admin_shift_add(request, pk):
    obj = get_object_or_404(User, pk=pk)
    form = ShiftForm(request.POST)
    if form.is_valid():
        shift = form.save(commit=False)
        shift.user = obj
        shift.save()
    return redirect("dashboard:admin_user_edit", pk=pk)


@admin_only
@require_POST
def admin_shift_delete(request, pk, shift_id):
    Shift.objects.filter(pk=shift_id, user_id=pk).delete()
    return redirect("dashboard:admin_user_edit", pk=pk)


@admin_only
def admin_clients(request):
    return render(request, "adminx/clients.html", {"clients": Client.objects.all()[:300]})


@admin_only
def admin_simulate(request):
    form = SimulateMessageForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        uploads = request.FILES.getlist("files")
        message = services.ingest_message(
            channel=form.cleaned_data["channel"],
            body=form.cleaned_data["body"],
            subject=form.cleaned_data["subject"],
            sender_identity=form.cleaned_data["sender_identity"],
            attachments=[
                {"file": f, "name": f.name, "size": f.size} for f in uploads
            ],
        )
        flash.success(request, message.client_code)
        return redirect("dashboard:admin_simulate")
    return render(request, "adminx/simulate.html", {
        "form": form,
        "recent": InboundMessage.objects.select_related("client")[:20],
    })


@admin_only
def admin_audit(request):
    from .models import AuditLog

    return render(request, "adminx/audit.html", {
        "logs": AuditLog.objects.select_related("actor")[:200]
    })


# ---------------------------------------------------------------------------
# Accounts
#
# The admin runs the month; the translator reads their own payslip. Nothing on
# these screens moves money on its own - a deduction has to be approved and the
# two monthly bonuses have to be released.
# ---------------------------------------------------------------------------

def _period_choices(limit=13):
    """The current month and the twelve before it."""
    today = timezone.localdate()
    out = []
    year, month = today.year, today.month
    for _ in range(limit):
        out.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def _requested_month(request):
    """Read the month off the query string. ``?period=2026-09`` is what the
    picker sends; ``?year=&month=`` is accepted so links stay readable."""
    today = timezone.localdate()
    source = request.POST if request.method == "POST" else request.GET
    period = source.get("period") or ""
    if "-" in period:
        head, _, tail = period.partition("-")
        raw_year, raw_month = head, tail
    else:
        raw_year = source.get("year") or today.year
        raw_month = source.get("month") or today.month
    try:
        year, month = int(raw_year), int(raw_month)
    except (TypeError, ValueError):
        return today.year, today.month
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        return today.year, today.month
    return year, month


@admin_only
def accounts_overview(request):
    year, month = _requested_month(request)
    period = PayrollPeriod.objects.filter(year=year, month=month).first()
    lines = (
        period.lines.select_related("user").all() if period else PayrollLine.objects.none()
    )
    return render(request, "accounts/overview.html", {
        "conf": PayrollSettings.load(),
        "year": year,
        "month": month,
        "period": period,
        "lines": lines,
        "totals": payroll.month_totals(period) if period else None,
        "periods": _period_choices(),
        "pending_violations": Violation.objects.filter(
            status=ApprovalStatus.PENDING
        ).select_related("user")[:50],
        "missing_salary": User.objects.filter(
            role=Role.TRANSLATOR, is_active=True, salary_records__isnull=True
        ),
        # A job whose word count nobody has settled would walk into the month
        # as a number that is either missing or unchecked. Say so before the
        # month is run, not after it is paid.
        "unsettled_tasks": Task.objects.filter(
            translated_at__date__range=payroll.month_bounds(year, month),
            word_count_state__in=(
                WordCountState.EMPTY, WordCountState.REVIEW,
                WordCountState.MANUAL_NEEDED,
            ),
        ).select_related("translator")[:30],
    })


@admin_only
@require_POST
def accounts_recalculate(request):
    year, month = _requested_month(request)
    period = payroll.compute_period(year, month, actor=request.user)
    if period.is_locked:
        flash.error(request, "الشهر مقفول - مش بيتحسب تاني.")
    else:
        flash.success(request, "اتحسب")
    return redirect(f"{reverse('dashboard:accounts_overview')}?year={year}&month={month}")


@admin_only
@require_POST
def accounts_period_approve(request, pk):
    period = get_object_or_404(PayrollPeriod, pk=pk)
    if period.is_locked:
        flash.error(request, "الشهر مقفول بالفعل.")
    else:
        payroll.approve_period(period, request.user, lock=request.POST.get("lock") == "1")
        flash.success(request, "اتعمد")
    return redirect(
        f"{reverse('dashboard:accounts_overview')}?year={period.year}&month={period.month}"
    )


@login_required
def accounts_line(request, pk):
    line = get_object_or_404(
        PayrollLine.objects.select_related("user", "period"), pk=pk
    )
    # A translator may read their own payslip and nobody else's.
    if not (request.user.is_admin_role or line.user_id == request.user.id):
        raise Http404
    return render(request, "accounts/line.html", {
        "line": line,
        "conf": PayrollSettings.load(),
        "days": line.breakdown.get("days", []),
        "deduction_rows": line.breakdown.get("deductions", []),
        "pending_rows": line.breakdown.get("pending", []),
    })


@admin_only
@require_POST
def accounts_line_bonus(request, pk):
    line = get_object_or_404(PayrollLine.objects.select_related("period"), pk=pk)
    if line.period.is_locked:
        flash.error(request, "الشهر مقفول.")
    else:
        payroll.approve_bonuses(line, request.user)
        flash.success(request, "المكافآت اتصرفت")
    return redirect("dashboard:accounts_line", pk=pk)


@admin_only
def accounts_attendance(request):
    year, month = _requested_month(request)
    first_day, last_day = payroll.month_bounds(year, month)
    people = User.objects.filter(role=Role.TRANSLATOR, is_active=True)

    person_id = request.GET.get("user")
    person = people.filter(pk=person_id).first() if person_id else people.first()

    form = WorkDayForm(request.POST or None)
    if request.method == "POST" and person is not None and form.is_valid():
        # One row per person per day, so a second save for the same date edits
        # the first instead of hitting the unique constraint.
        existing = WorkDay.objects.filter(
            user=person, date=form.cleaned_data["date"]
        ).first()
        if existing is not None:
            form = WorkDayForm(request.POST, instance=existing)
            form.is_valid()
        day = form.save(commit=False)
        day.user = person
        day.save()
        services.log(request.user, "workday.save", f"{person.username} {day.date}")
        flash.success(request, "اتسجل")
        return redirect(
            f"{reverse('dashboard:accounts_attendance')}"
            f"?year={year}&month={month}&user={person.pk}"
        )

    conf = PayrollSettings.load()
    days = []
    if person is not None:
        payroll.refresh_words(person, first_day, last_day)
        days = list(WorkDay.objects.filter(
            user=person, date__range=(first_day, last_day)
        ).order_by("date"))
        # Resolved once here so the table does not reload the settings per row.
        for day in days:
            day.under_floor = day.is_under_target(conf)

    return render(request, "accounts/attendance.html", {
        "conf": conf,
        "form": form,
        "people": people,
        "person": person,
        "days": days,
        "year": year,
        "month": month,
        "periods": _period_choices(),
        "leave_used": sum(1 for d in days if d.status in LEAVE_STATUSES),
        "words": sum(d.words for d in days if d.is_working_day),
    })


@admin_only
def accounts_violations(request):
    form = ViolationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        row.created_by = request.user
        row.save()
        services.log(request.user, "violation.create", f"{row.user.username} {row.kind}")
        flash.success(request, "اتسجلت - مستنية الاعتماد")
        return redirect("dashboard:accounts_violations")

    return render(request, "accounts/violations.html", {
        "form": form,
        "pending": Violation.objects.filter(
            status=ApprovalStatus.PENDING
        ).select_related("user", "task"),
        "decided": Violation.objects.exclude(
            status=ApprovalStatus.PENDING
        ).select_related("user", "approved_by")[:60],
        "conf": PayrollSettings.load(),
    })


@admin_only
@require_POST
def accounts_violation_decide(request, pk, action):
    row = get_object_or_404(Violation, pk=pk)
    if action == "approve":
        row.approve(request.user)
    elif action == "reject":
        row.reject(request.user)
    else:
        raise Http404
    services.log(request.user, f"violation.{action}", f"{row.user.username} {row.date}")
    return redirect(request.POST.get("next") or "dashboard:accounts_violations")


@admin_only
def accounts_rules(request):
    conf = PayrollSettings.load()
    form = PayrollSettingsForm(request.POST or None, instance=conf)
    tier_form = ProductionTierForm()

    if request.method == "POST" and form.is_valid():
        form.save()
        services.log(request.user, "payroll.rules.update")
        flash.success(request, "اتحفظ")
        return redirect("dashboard:accounts_rules")

    return render(request, "accounts/rules.html", {
        "form": form,
        "conf": conf,
        "tier_form": tier_form,
        "primary": ProductionTier.objects.filter(scale=TierScale.PRIMARY),
        "secondary": ProductionTier.objects.filter(scale=TierScale.SECONDARY),
    })


@admin_only
@require_POST
def accounts_tier_add(request):
    form = ProductionTierForm(request.POST)
    if form.is_valid():
        form.save()
        services.log(request.user, "payroll.tier.add")
    else:
        flash.error(request, "الشريحة مش مظبوطة.")
    return redirect("dashboard:accounts_rules")


@admin_only
@require_POST
def accounts_tier_delete(request, pk):
    ProductionTier.objects.filter(pk=pk).delete()
    services.log(request.user, "payroll.tier.delete", str(pk))
    return redirect("dashboard:accounts_rules")


@admin_only
def accounts_salary(request, pk):
    person = get_object_or_404(User, pk=pk)
    form = SalaryRecordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        row.user = person
        row.created_by = request.user
        row.save()
        # History is append-only: an old month keeps the salary it was paid on.
        services.log(request.user, "salary.set", person.username, str(row.amount))
        flash.success(request, "اتسجل")
        return redirect("dashboard:accounts_salary", pk=pk)

    return render(request, "accounts/salary.html", {
        "person": person,
        "form": form,
        "records": person.salary_records.all(),
        "lines": person.payroll_lines.select_related("period")[:24],
    })


@role_required(Role.TRANSLATOR)
def translator_payroll(request):
    """The translator's own payslip - read only, and only ever their own."""
    year, month = _requested_month(request)
    line = PayrollLine.objects.filter(
        user=request.user, period__year=year, period__month=month
    ).select_related("period").first()
    first_day, last_day = payroll.month_bounds(year, month)
    return render(request, "accounts/mine.html", {
        "line": line,
        "conf": PayrollSettings.load(),
        "year": year,
        "month": month,
        "periods": _period_choices(),
        "days": WorkDay.objects.filter(
            user=request.user, date__range=(first_day, last_day)
        ).order_by("date"),
        "violations": Violation.objects.filter(
            user=request.user, date__range=(first_day, last_day)
        ),
    })
