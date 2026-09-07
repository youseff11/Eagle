"""Page views for the Eagle dashboard."""

from django.contrib import messages as flash
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    AICheckForm,
    ClientForm,
    RequirementForm,
    SettingsForm,
    ShiftForm,
    SimulateMessageForm,
    StaffCreateForm,
    StaffEditForm,
    TaskForm,
)
from .models import (
    ACTIVE_TASK_STATUSES,
    AppSettings,
    AssignmentStatus,
    Client,
    InboundMessage,
    Notification,
    Role,
    RoomKind,
    Shift,
    Task,
    TaskStatus,
    User,
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
# Operation
# ---------------------------------------------------------------------------

@role_required(Role.OPERATION)
def ops_inbox(request):
    user = request.user
    qs = InboundMessage.objects.select_related("client", "claimed_by").prefetch_related(
        "attachments"
    )
    if not user.is_admin_role:
        qs = qs.filter(is_rate_blocked=False)

    state = request.GET.get("state", "")
    if state == "unclaimed":
        qs = qs.filter(claimed_by__isnull=True)
    elif state == "mine":
        qs = qs.filter(claimed_by=user)
    elif state == "notask":
        qs = qs.filter(task__isnull=True)

    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(Q(body__icontains=query) | Q(client__code__icontains=query))

    context = {
        "messages_list": qs[:150],
        "state": state,
        "query": query,
        "unclaimed_count": InboundMessage.objects.filter(
            claimed_by__isnull=True, is_rate_blocked=False
        ).count(),
        "blocked_count": InboundMessage.objects.filter(is_rate_blocked=True).count(),
    }
    return render(request, "ops/inbox.html", context)


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

    rooms = list(services.rooms_for(task, user))
    active_room = None
    room_id = request.GET.get("room")
    if room_id:
        active_room = next((r for r in rooms if str(r.id) == str(room_id)), None)
    if active_room is None and rooms:
        active_room = rooms[-1]

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

    chat_messages = list(
        active_room.messages.select_related("sender").prefetch_related("attachments")
    ) if active_room else []

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
        "source_messages": (
            task.source_messages.prefetch_related("attachments")
            if (user.is_operation or user.is_admin_role) else []
        ),
        "conf": AppSettings.load(),
    }
    return render(request, "shared/task_detail.html", context)


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


@login_required
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
    if request.method == "POST" and form.is_valid():
        form.save()
        services.log(request.user, "settings.update")
        flash.success(request, "saved")
        return redirect("dashboard:admin_settings")
    return render(request, "adminx/settings.html", {"form": form, "conf": conf})


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
