"""Page views for the Eagle dashboard."""

from datetime import datetime, timedelta

from django.contrib import messages as flash
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import attendance, employees, payroll, performance, recruitment, services, wordcount
from .forms import (
    AICheckForm,
    AttendanceEditForm,
    CandidateForm,
    ClientComplaintForm,
    CandidateMessageForm,
    CandidateTestForm,
    ClientForm,
    DepartmentForm,
    HireForm,
    InterviewForm,
    InterviewScoreForm,
    LeaveDecisionForm,
    LeaveRequestForm,
    ProbationDecisionForm,
    OfficeLocationForm,
    PayrollSettingsForm,
    ProductionTierForm,
    RequirementForm,
    SalaryRecordForm,
    ScheduleOverrideForm,
    RecruitmentQuestionForm,
    RecruitmentSettingsForm,
    SalaryChangeRequestForm,
    SalaryPlanForm,
    SettingsForm,
    ShiftForm,
    ShiftTemplateForm,
    SimulateMessageForm,
    StaffCreateForm,
    StaffEditForm,
    TaskForm,
    TestScoreForm,
    VacancyForm,
    ViolationForm,
    WorkDayForm,
)
from .models import (
    ACTIVE_TASK_STATUSES,
    DAY_WORK_MODES,
    LEAVE_STATUSES,
    ApprovalStatus,
    AppSettings,
    AssignmentStatus,
    AuthorizedDevice,
    Candidate,
    CandidateSource,
    CandidateStatus,
    CandidateTest,
    ChatAttachment,
    ClientComplaint,
    ChatRoom,
    Client,
    DayStatus,
    Department,
    EmploymentStatus,
    Interview,
    LeaveRequest,
    LeaveStatus,
    InboundMessage,
    Notification,
    OfficeLocation,
    OvertimeClaim,
    PayrollLine,
    PayrollPeriod,
    PayrollSettings,
    ProbationOutcome,
    ProbationReview,
    ProductionTier,
    RecruitmentQuestion,
    RecruitmentSettings,
    Role,
    RoomKind,
    SalaryChangeRequest,
    SalaryPlan,
    SalaryRecord,
    ScheduleOverride,
    Shift,
    ShiftTemplate,
    Task,
    TaskStatus,
    TierScale,
    User,
    Vacancy,
    VacancyQuestion,
    VacancyStatus,
    Violation,
    WordCountState,
    WorkDay,
    WorkMode,
)
from .permissions import (
    accounting_only,
    admin_only,
    hr_required,
    owner_required,
    recruit_required,
    reviewer_required,
    role_required,
    user_may_open,
)


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
        # Safe to redirect to is not the same question as allowed to open. A
        # translator arriving from a link to /panel/ used to sign in fine and
        # land on a bare 403; now the door they cannot open simply drops them
        # at their own one.
        if (
            nxt
            and url_has_allowed_host_and_scheme(
                nxt,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            )
            and user_may_open(request.user, nxt)
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
    if user.is_hr:
        return redirect("dashboard:hr_recruitment")
    if user.is_reviewer:
        return redirect("dashboard:reviewer_tests")
    if user.is_accounting:
        return redirect("dashboard:accounts_overview")
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

    # An admin who claimed the client's message themselves opens the group
    # without an operation in it. These are the people they can still add.
    group_room = task.rooms.filter(kind=RoomKind.GROUP).first()
    group_candidates = []
    if user.is_admin_role and group_room is not None:
        group_candidates = (
            User.objects
            .filter(is_active=True, role__in=(Role.OPERATION, Role.TEAM_LEAD))
            .exclude(pk__in=group_room.members.values("pk"))
        )

    context = {
        "task": task,
        "rooms": rooms,
        "group_candidates": group_candidates,
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


@accounting_only
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


@accounting_only
@require_POST
def accounts_recalculate(request):
    year, month = _requested_month(request)
    period = payroll.compute_period(year, month, actor=request.user)
    if period.is_locked:
        flash.error(request, "الشهر مقفول - مش بيتحسب تاني.")
    else:
        flash.success(request, "اتحسب")
    return redirect(f"{reverse('dashboard:accounts_overview')}?year={year}&month={month}")


@accounting_only
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


@accounting_only
@require_POST
def accounts_line_bonus(request, pk):
    line = get_object_or_404(PayrollLine.objects.select_related("period"), pk=pk)
    if line.period.is_locked:
        flash.error(request, "الشهر مقفول.")
    else:
        payroll.approve_bonuses(line, request.user)
        flash.success(request, "المكافآت اتصرفت")
    return redirect("dashboard:accounts_line", pk=pk)


@accounting_only
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
        # Hours typed here still have to agree with the attendance engine, or
        # the payroll sheet and the monthly report would tell two stories.
        attendance.recompute(day)
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


@accounting_only
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


@accounting_only
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


@accounting_only
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


# ---------------------------------------------------------------------------
# Attendance - the person's own card
# ---------------------------------------------------------------------------

@login_required
def my_attendance(request):
    """Check in, break, check out - and the last fortnight, read only.

    Nothing on this page can be edited. A punch that came out wrong is fixed
    by HR with a reason attached, which is the whole point of section 9.
    """
    user = request.user
    today = timezone.localdate()
    plan = attendance.plan_for(user, today)
    day, _resolved = attendance.resolve_work_date(user)
    row = WorkDay.objects.filter(user=user, date=day).first()

    recent = (
        WorkDay.objects.filter(user=user, date__lte=today)
        .order_by("-date")[:14]
    )
    conf = PayrollSettings.load()
    return render(request, "attendance/mine.html", {
        "conf": conf,
        "plan": plan,
        "row": row,
        "work_date": day,
        "recent": recent,
        "needs_location": (
            row.is_office_day if row is not None
            else plan.mode == WorkMode.OFFICE
        ),
        "summary": attendance.month_summary(
            user, *payroll.month_bounds(today.year, today.month)
        ),
        "devices": user.devices.all()[:6],
    })


# ---------------------------------------------------------------------------
# Attendance - the HR board
# ---------------------------------------------------------------------------

def _range_for(request):
    """Read ``?view=day|week|month`` and ``?date=`` into a real date range."""
    mode = request.GET.get("view") or "day"
    raw = request.GET.get("date") or ""
    try:
        anchor = datetime.strptime(raw, "%Y-%m-%d").date() if raw else timezone.localdate()
    except ValueError:
        anchor = timezone.localdate()

    if mode == "week":
        # Saturday-first, because the Egyptian working week is.
        start = anchor - timedelta(days=(anchor.weekday() + 2) % 7)
        return mode, anchor, start, start + timedelta(days=6)
    if mode == "month":
        return (mode, anchor) + payroll.month_bounds(anchor.year, anchor.month)
    return mode, anchor, anchor, anchor


@hr_required
def hr_attendance(request):
    """Everybody's attendance for a day, a week or a month, with filters."""
    mode, anchor, first_day, last_day = _range_for(request)

    people = User.objects.filter(is_active=True, attendance_enabled=True)
    if request.GET.get("role"):
        people = people.filter(role=request.GET["role"])
    if request.GET.get("user"):
        people = people.filter(pk=request.GET["user"])
    if request.GET.get("mode"):
        people = people.filter(work_mode=request.GET["mode"])

    rows = (
        WorkDay.objects.filter(user__in=people, date__range=(first_day, last_day))
        .select_related("user").order_by("-date", "user__username")
    )
    if request.GET.get("status"):
        rows = rows.filter(status=request.GET["status"])
    if request.GET.get("day_mode"):
        rows = rows.filter(work_mode=request.GET["day_mode"])
    if request.GET.get("shift"):
        rows = rows.filter(schedule_label=request.GET["shift"])
    if request.GET.get("flagged") == "1":
        rows = rows.filter(needs_review=True)

    rows = list(rows[:600])

    # Who was rostered today and has no row at all - the people a status
    # table would otherwise render invisible.
    missing = []
    if mode == "day":
        recorded = {r.user_id for r in rows}
        for person in people:
            if person.pk in recorded:
                continue
            plan = attendance.plan_for(person, anchor)
            if plan.working:
                missing.append({"user": person, "plan": plan})

    return render(request, "hr/attendance.html", {
        "conf": PayrollSettings.load(),
        "rows": rows,
        "missing": missing,
        "people": User.objects.filter(is_active=True, attendance_enabled=True),
        "mode": mode,
        "anchor": anchor,
        "first_day": first_day,
        "last_day": last_day,
        "roles": Role.choices,
        "statuses": DayStatus.choices,
        "day_modes": DAY_WORK_MODES,
        "shifts": ShiftTemplate.objects.all(),
        "flagged_count": WorkDay.objects.filter(needs_review=True).count(),
        "selected": request.GET,
        "totals": {
            "present": sum(1 for r in rows if r.status == DayStatus.PRESENT),
            "late": sum(1 for r in rows if r.late_minutes),
            "off_site": sum(1 for r in rows if r.off_site),
            "open": sum(1 for r in rows if r.is_open),
            "minutes": sum(r.work_minutes for r in rows),
            "overtime": sum(r.overtime_minutes for r in rows),
        },
    })


@hr_required
def hr_attendance_day(request, pk):
    """One day, its punches, its corrections - and the form that adds more."""
    row = get_object_or_404(WorkDay.objects.select_related("user"), pk=pk)
    form = AttendanceEditForm(request.POST or None, instance=row)

    if request.method == "POST" and form.is_valid():
        # The form's instance is already mutated by ModelForm, so the "before"
        # values have to come from a clean read of the row.
        fresh = WorkDay.objects.get(pk=row.pk)
        changes = {name: form.cleaned_data[name] for name in form.Meta.fields}
        try:
            written = attendance.apply_edit(
                fresh, request.user, changes, form.cleaned_data["reason"]
            )
        except attendance.PunchRefused as refused:
            flash.error(request, refused.ar)
        else:
            flash.success(
                request, f"{len(written)} تعديل" if written else "مفيش حاجة اتغيرت"
            )
            return redirect("dashboard:hr_attendance_day", pk=pk)

    return render(request, "hr/attendance_day.html", {
        "row": row,
        "form": form,
        "events": row.events.select_related("office", "device").all(),
        "edits": row.edits.select_related("actor").all(),
        "conf": PayrollSettings.load(),
    })


@hr_required
@require_POST
def hr_attendance_clear(request, pk):
    row = get_object_or_404(WorkDay, pk=pk)
    attendance.clear_review(row, request.user, request.POST.get("reason", ""))
    flash.success(request, "اتراجع")
    return redirect(request.POST.get("next") or "dashboard:hr_attendance")


@hr_required
def hr_report(request):
    """Section 12, for one person and one month."""
    year, month = _requested_month(request)
    first_day, last_day = payroll.month_bounds(year, month)
    people = User.objects.filter(is_active=True, attendance_enabled=True)
    person_id = request.GET.get("user")
    person = people.filter(pk=person_id).first() if person_id else people.first()

    summary = (
        attendance.month_summary(person, first_day, last_day) if person else None
    )
    return render(request, "hr/report.html", {
        "people": people,
        "person": person,
        "summary": summary,
        "year": year,
        "month": month,
        "periods": _period_choices(),
        "conf": PayrollSettings.load(),
    })


# ---------------------------------------------------------------------------
# Attendance - schedules, offices, devices, overtime
# ---------------------------------------------------------------------------

@hr_required
def hr_schedules(request):
    """A person's standing roster, plus the one-off days that override it."""
    people = User.objects.filter(is_active=True)
    person_id = request.GET.get("user") or request.POST.get("user")
    person = people.filter(pk=person_id).first() if person_id else people.first()

    shift_form = ShiftForm()
    override_form = ScheduleOverrideForm()
    action = request.POST.get("action") if request.method == "POST" else ""

    if action == "shift" and person is not None:
        shift_form = ShiftForm(request.POST)
        if shift_form.is_valid():
            row = shift_form.save(commit=False)
            row.user = person
            row.save()
            services.log(request.user, "schedule.shift.add", f"{person.username} {row.weekday}")
            flash.success(request, "اتسجل")
            return redirect(f"{reverse('dashboard:hr_schedules')}?user={person.pk}")

    if action == "override" and person is not None:
        override_form = ScheduleOverrideForm(request.POST)
        if override_form.is_valid():
            row = override_form.save(commit=False)
            row.user = person
            row.created_by = request.user
            # One override per date: saving the same day twice edits it.
            ScheduleOverride.objects.filter(user=person, date=row.date).delete()
            row.save()
            services.log(request.user, "schedule.override", f"{person.username} {row.date}")
            flash.success(request, "اتسجل")
            return redirect(f"{reverse('dashboard:hr_schedules')}?user={person.pk}")

    # The coming fortnight, resolved - so HR sees what the rules actually say
    # rather than having to replay the roster in their head.
    preview = []
    if person is not None:
        today = timezone.localdate()
        for offset in range(14):
            day = today + timedelta(days=offset)
            preview.append(attendance.plan_for(person, day))

    return render(request, "hr/schedules.html", {
        "people": people,
        "person": person,
        "shift_form": shift_form,
        "override_form": override_form,
        "shifts": person.shifts.select_related("template").all() if person else [],
        "overrides": (
            person.schedule_overrides.select_related("template")
            .filter(date__gte=timezone.localdate() - timedelta(days=30))
            if person else []
        ),
        "templates": ShiftTemplate.objects.all(),
        "template_form": ShiftTemplateForm(),
        "preview": preview,
    })


@hr_required
@require_POST
def hr_shift_delete(request, pk):
    row = get_object_or_404(Shift, pk=pk)
    person_id = row.user_id
    row.delete()
    services.log(request.user, "schedule.shift.delete", str(pk))
    return redirect(f"{reverse('dashboard:hr_schedules')}?user={person_id}")


@hr_required
@require_POST
def hr_override_delete(request, pk):
    row = get_object_or_404(ScheduleOverride, pk=pk)
    person_id = row.user_id
    row.delete()
    services.log(request.user, "schedule.override.delete", str(pk))
    return redirect(f"{reverse('dashboard:hr_schedules')}?user={person_id}")


@hr_required
@require_POST
def hr_template_add(request):
    form = ShiftTemplateForm(request.POST)
    if form.is_valid():
        form.save()
        services.log(request.user, "schedule.template.add")
        flash.success(request, "اتسجل")
    else:
        flash.error(request, "الشيفت مش مظبوط.")
    return redirect(request.POST.get("next") or "dashboard:hr_schedules")


@hr_required
def hr_offices(request):
    """Where a punch may be made from. Empty means no location check at all."""
    form = OfficeLocationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        services.log(request.user, "attendance.office.add", form.cleaned_data["name"])
        flash.success(request, "اتسجل")
        return redirect("dashboard:hr_offices")

    return render(request, "hr/offices.html", {
        "form": form,
        "offices": OfficeLocation.objects.all(),
        "conf": PayrollSettings.load(),
    })


@hr_required
@require_POST
def hr_office_delete(request, pk):
    OfficeLocation.objects.filter(pk=pk).delete()
    services.log(request.user, "attendance.office.delete", str(pk))
    return redirect("dashboard:hr_offices")


@hr_required
def hr_devices(request):
    return render(request, "hr/devices.html", {
        "pending": AuthorizedDevice.objects.filter(
            status=ApprovalStatus.PENDING
        ).select_related("user"),
        "decided": AuthorizedDevice.objects.exclude(
            status=ApprovalStatus.PENDING
        ).select_related("user", "approved_by")[:60],
        "conf": PayrollSettings.load(),
    })


@hr_required
@require_POST
def hr_device_decide(request, pk, action):
    device = get_object_or_404(AuthorizedDevice, pk=pk)
    if action == "approve":
        device.approve(request.user)
    elif action == "reject":
        device.reject(request.user)
    else:
        raise Http404
    services.log(request.user, f"attendance.device.{action}", device.user.username)
    return redirect("dashboard:hr_devices")


@hr_required
def hr_overtime(request):
    """Extra hours waiting on a decision - the mirror of the violations page."""
    return render(request, "hr/overtime.html", {
        "pending": OvertimeClaim.objects.filter(
            status=ApprovalStatus.PENDING
        ).select_related("user"),
        "decided": OvertimeClaim.objects.exclude(
            status=ApprovalStatus.PENDING
        ).select_related("user", "approved_by")[:60],
        "conf": PayrollSettings.load(),
    })


@hr_required
@require_POST
def hr_overtime_decide(request, pk, action):
    claim = get_object_or_404(OvertimeClaim, pk=pk)
    if action == "approve":
        claim.approve(request.user)
    elif action == "reject":
        claim.reject(request.user)
    else:
        raise Http404
    services.log(
        request.user, f"attendance.overtime.{action}", f"{claim.user.username} {claim.date}"
    )
    return redirect(request.POST.get("next") or "dashboard:hr_overtime")


# ---------------------------------------------------------------------------
# HR / recruitment
#
# Every screen here obeys one rule the spec insists on: nothing the candidate
# reads carries the company's name until HR has deliberately revealed it. The
# enforcement is in `recruitment.outbound_text`, not in these views - a rule
# that lives in a template is a rule with a hole in it.
# ---------------------------------------------------------------------------

@recruit_required
def hr_recruitment(request):
    """Section 26, the pipeline at a glance."""
    conf = RecruitmentSettings.load()
    return render(request, "hr/recruitment.html", {
        "conf": conf,
        "counts": recruitment.dashboard_counts(),
        "recent": Candidate.objects.select_related("vacancy")[:15],
        "today_interviews": Interview.objects.filter(
            scheduled_at__date=timezone.localdate()
        ).select_related("candidate", "interviewer"),
        "waiting_owner": Candidate.objects.filter(
            status=CandidateStatus.OWNER_APPROVAL
        ).select_related("vacancy")[:10],
        "recruit_number": AppSettings.load().recruit_number_display,
        # If nothing is configured to redact, section 3 is not being enforced
        # and the screen should say so rather than imply it is.
        "privacy_armed": bool(conf.term_list),
    })


@recruit_required
def hr_vacancies(request):
    form = VacancyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        row.created_by = request.user
        row.save()
        form.save_m2m()
        services.log(request.user, "recruitment.vacancy.create", row.code, row.title)
        flash.success(request, "اتسجلت")
        return redirect("dashboard:hr_vacancy", code=row.code)

    rows = Vacancy.objects.select_related("department").annotate(
        applicants=Count("candidates")
    )
    status = request.GET.get("status")
    if status:
        rows = rows.filter(status=status)
    return render(request, "hr/vacancies.html", {
        "form": form,
        "rows": rows,
        "statuses": VacancyStatus.choices,
        "selected": request.GET,
    })


@recruit_required
def hr_vacancy(request, code):
    """One vacancy: its details, and the questions the bot will ask for it."""
    vacancy = get_object_or_404(Vacancy.objects.select_related("department"), code=code)
    form = VacancyForm(request.POST or None, instance=vacancy)
    action = request.POST.get("action") if request.method == "POST" else ""

    if action == "save" and form.is_valid():
        form.save()
        services.log(request.user, "recruitment.vacancy.update", vacancy.code)
        flash.success(request, "اتحفظت")
        return redirect("dashboard:hr_vacancy", code=code)

    if action == "add_question":
        question = RecruitmentQuestion.objects.filter(
            pk=request.POST.get("question"), is_active=True
        ).first()
        if question is not None:
            last = vacancy.question_links.count()
            VacancyQuestion.objects.get_or_create(
                vacancy=vacancy, question=question,
                defaults={"order": last + 1, "is_required": True},
            )
            services.log(request.user, "recruitment.vacancy.question", vacancy.code)
        return redirect("dashboard:hr_vacancy", code=code)

    if action == "order":
        # One POST carries the whole list, so a reorder is a single save.
        for link in vacancy.question_links.all():
            raw = request.POST.get(f"order_{link.pk}")
            if raw and raw.isdigit():
                link.order = int(raw)
            link.is_required = request.POST.get(f"required_{link.pk}") == "1"
            link.save(update_fields=["order", "is_required"])
        flash.success(request, "اتحفظ الترتيب")
        return redirect("dashboard:hr_vacancy", code=code)

    chosen = vacancy.question_links.values_list("question_id", flat=True)
    pool = RecruitmentQuestion.objects.filter(is_active=True).exclude(pk__in=chosen)
    if vacancy.department_id:
        # The department narrows the list; it never dictates it (section 11).
        pool = pool.filter(
            Q(department_id=vacancy.department_id) | Q(department__isnull=True)
        )
    return render(request, "hr/vacancy.html", {
        "vacancy": vacancy,
        "form": form,
        "links": vacancy.questions_in_order(),
        "pool": pool.select_related("department"),
        "candidates": vacancy.candidates.all()[:30],
    })


@recruit_required
@require_POST
def hr_vacancy_question_delete(request, pk):
    link = get_object_or_404(VacancyQuestion.objects.select_related("vacancy"), pk=pk)
    code = link.vacancy.code
    link.delete()
    services.log(request.user, "recruitment.vacancy.question.remove", code)
    return redirect("dashboard:hr_vacancy", code=code)


@recruit_required
def hr_questions(request):
    """The central bank. HR writes the questions; the code never does."""
    editing = RecruitmentQuestion.objects.filter(pk=request.GET.get("edit")).first()
    form = RecruitmentQuestionForm(request.POST or None, instance=editing)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        if not row.pk:
            row.created_by = request.user
        row.save()
        services.log(request.user, "recruitment.question.save", str(row.pk), row.text[:80])
        flash.success(request, "اتحفظ")
        return redirect("dashboard:hr_questions")

    rows = RecruitmentQuestion.objects.select_related("department")
    if request.GET.get("department"):
        rows = rows.filter(department_id=request.GET["department"])
    return render(request, "hr/questions.html", {
        "form": form,
        "editing": editing,
        "rows": rows,
        "departments": Department.objects.filter(is_active=True),
        "department_form": DepartmentForm(),
        "selected": request.GET,
    })


@recruit_required
@require_POST
def hr_department_add(request):
    form = DepartmentForm(request.POST)
    if form.is_valid():
        form.save()
        services.log(request.user, "recruitment.department.add", form.cleaned_data["name"])
        flash.success(request, "اتسجل")
    else:
        flash.error(request, "القسم مش مظبوط.")
    return redirect("dashboard:hr_questions")


@recruit_required
def hr_candidates(request):
    rows = Candidate.objects.select_related("vacancy", "department")
    for field in ("status", "source"):
        if request.GET.get(field):
            rows = rows.filter(**{field: request.GET[field]})
    if request.GET.get("vacancy"):
        rows = rows.filter(vacancy__code=request.GET["vacancy"])
    query = (request.GET.get("q") or "").strip()
    if query:
        rows = rows.filter(
            Q(full_name__icontains=query) | Q(phone__icontains=query)
            | Q(code__icontains=query) | Q(email__icontains=query)
        )
    return render(request, "hr/candidates.html", {
        "rows": rows[:300],
        "statuses": CandidateStatus.choices,
        "sources": CandidateSource.choices,
        "vacancies": Vacancy.objects.all(),
        "selected": request.GET,
        "counts": recruitment.dashboard_counts(),
    })


@recruit_required
def hr_candidate(request, code):
    """The whole application on one page, plus every action HR can take."""
    candidate = get_object_or_404(
        Candidate.objects.select_related("vacancy", "department", "hired_user"), code=code
    )
    form = CandidateForm(request.POST or None, request.FILES or None, instance=candidate)
    interview_form = InterviewForm()
    test_form = CandidateTestForm()
    message_form = CandidateMessageForm()
    action = request.POST.get("action") if request.method == "POST" else ""

    if action == "save" and form.is_valid():
        form.save()
        services.log(request.user, "recruitment.candidate.update", candidate.code)
        flash.success(request, "اتحفظ")
        return redirect("dashboard:hr_candidate", code=code)

    if action == "status":
        try:
            recruitment.move_status(
                candidate, request.POST.get("status", ""), request.user,
                request.POST.get("reason", ""),
            )
        except recruitment.PipelineError as refused:
            flash.error(request, refused.ar)
        else:
            flash.success(request, "اتغيرت الحالة")
        return redirect("dashboard:hr_candidate", code=code)

    if action == "reveal":
        recruitment.reveal_identity(
            candidate, request.user, request.POST.get("reason", "")
        )
        flash.success(request, "الهوية اتكشفت للمرشح ده")
        return redirect("dashboard:hr_candidate", code=code)

    if action == "interview":
        interview_form = InterviewForm(request.POST)
        if interview_form.is_valid():
            row = interview_form.save(commit=False)
            row.candidate = candidate
            row.created_by = request.user
            row.save()
            services.log(request.user, "recruitment.interview.schedule", candidate.code)
            flash.success(request, "المقابلة اتسجلت")
            return redirect("dashboard:hr_candidate", code=code)

    if action == "test":
        test_form = CandidateTestForm(request.POST, request.FILES)
        if test_form.is_valid():
            row = test_form.save(commit=False)
            row.candidate = candidate
            row.department = row.department or candidate.department
            row.created_by = request.user
            if row.assignment:
                row.assignment_name = row.assignment.name[:200]
            row.save()
            services.log(request.user, "recruitment.test.assign", candidate.code)
            flash.success(request, "الاختبار اتسجل")
            return redirect("dashboard:hr_candidate", code=code)

    if action == "message":
        message_form = CandidateMessageForm(request.POST)
        if message_form.is_valid():
            ok, error = recruitment.send_to_candidate(
                candidate, message_form.cleaned_data["body"]
            )
            if ok:
                services.log(request.user, "recruitment.message", candidate.code)
                flash.success(request, "الرسالة اتبعتت")
            else:
                flash.error(request, f"مابعتتش: {error}")
            return redirect("dashboard:hr_candidate", code=code)

    conf = RecruitmentSettings.load()
    return render(request, "hr/candidate.html", {
        "candidate": candidate,
        "form": form,
        "interview_form": interview_form,
        "test_form": test_form,
        "message_form": message_form,
        "answers": candidate.answers.select_related("question").all(),
        "interviews": candidate.interviews.select_related("interviewer").all(),
        "tests": candidate.tests.select_related("reviewer").all(),
        "sessions": candidate.sessions.all()[:3],
        "next_statuses": recruitment.ALLOWED_MOVES.get(candidate.status, ()),
        "status_labels": dict(CandidateStatus.choices),
        "conf": conf,
        "privacy_armed": bool(conf.term_list),
    })


@recruit_required
def hr_interview_score(request, pk):
    interview = get_object_or_404(
        Interview.objects.select_related("candidate"), pk=pk
    )
    form = InterviewScoreForm(request.POST or None, instance=interview)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        row.evaluated_at = timezone.now()
        row.evaluated_by = request.user
        row.save()
        services.log(
            request.user, "recruitment.interview.score",
            interview.candidate.code, f"{row.total_score}/{row.max_score}",
        )
        flash.success(request, "التقييم اتسجل")
        return redirect("dashboard:hr_candidate", code=interview.candidate.code)

    return render(request, "hr/interview_score.html", {
        "interview": interview,
        "form": form,
        "fields": [(name, form[name]) for name in Interview.SCORE_FIELDS],
    })


@reviewer_required
def reviewer_tests(request):
    """The reviewer's own queue - tests and nothing else (section 24)."""
    mine = CandidateTest.objects.select_related("candidate", "department")
    if not request.user.is_admin_role:
        mine = mine.filter(Q(reviewer=request.user) | Q(reviewer__isnull=True))
    return render(request, "hr/reviewer_tests.html", {
        "pending": mine.filter(marked_at__isnull=True),
        "done": mine.filter(marked_at__isnull=False)[:40],
    })


@reviewer_required
def hr_test_score(request, pk):
    test = get_object_or_404(CandidateTest.objects.select_related("candidate"), pk=pk)
    form = TestScoreForm(request.POST or None, request.FILES or None, instance=test)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        if row.submission and not row.submitted_at:
            row.submitted_at = timezone.now()
            row.submission_name = row.submission.name[:200]
        row.marked_at = timezone.now()
        row.reviewer = row.reviewer or request.user
        row.save()
        services.log(
            request.user, "recruitment.test.score", test.candidate.code,
            f"{row.total_score}/{row.max_score}",
        )
        flash.success(request, "التقييم اتسجل")
        return redirect("dashboard:reviewer_tests")

    return render(request, "hr/test_score.html", {
        "test": test,
        "form": form,
        "fields": [(name, form[name]) for name in CandidateTest.SCORE_FIELDS],
        # The reviewer sees the work, not who the person is or what they want
        # to be paid. Section 24 keeps recruitment data away from this role.
        "blind": not request.user.is_admin_role,
    })


@owner_required
def hr_approvals(request):
    """Section 16. The owner's queue, and the only place a hire is decided."""
    return render(request, "hr/approvals.html", {
        "waiting": Candidate.objects.filter(
            status=CandidateStatus.OWNER_APPROVAL
        ).select_related("vacancy", "department"),
        "decided": Candidate.objects.filter(
            status__in=(CandidateStatus.APPROVED, CandidateStatus.HIRED)
        ).select_related("vacancy")[:30],
    })


@owner_required
@require_POST
def hr_approval_decide(request, code, action):
    candidate = get_object_or_404(Candidate, code=code)
    try:
        recruitment.decide_hiring(
            candidate, request.user, approve=(action == "approve"),
            reason=request.POST.get("reason", ""),
        )
    except recruitment.PipelineError as refused:
        flash.error(request, refused.ar)
    else:
        flash.success(request, "اتسجل القرار")
    return redirect(request.POST.get("next") or "dashboard:hr_approvals")


@recruit_required
def hr_hire(request, code):
    """Section 17: the approved candidate becomes an employee, once."""
    candidate = get_object_or_404(
        Candidate.objects.select_related("vacancy", "department"), code=code
    )
    form = HireForm(request.POST or None, initial={
        "job_title": candidate.vacancy.title if candidate.vacancy else "",
        "joining_date": timezone.localdate(),
    })
    if request.method == "POST" and form.is_valid():
        try:
            person = recruitment.hire(
                candidate, request.user,
                role=form.cleaned_data["role"],
                job_title=form.cleaned_data["job_title"],
                joining_date=form.cleaned_data["joining_date"],
                salary=form.cleaned_data["salary"],
                team_lead=form.cleaned_data["team_lead"],
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )
        except recruitment.PipelineError as refused:
            flash.error(request, refused.ar)
        else:
            flash.success(request, f"اتعيّن: {person.username}")
            return redirect("dashboard:hr_employee", pk=person.pk)

    return render(request, "hr/hire.html", {"candidate": candidate, "form": form})


@recruit_required
def hr_employees(request):
    rows = User.objects.filter(is_active=True).select_related("department", "team_lead")
    if request.GET.get("department"):
        rows = rows.filter(department_id=request.GET["department"])
    if request.GET.get("status"):
        rows = rows.filter(employment_status=request.GET["status"])
    return render(request, "hr/employees.html", {
        "rows": rows,
        "departments": Department.objects.filter(is_active=True),
        "statuses": EmploymentStatus.choices,
        "selected": request.GET,
    })


@recruit_required
def hr_employee(request, pk):
    """Section 18, with section 21's attendance read straight off the module."""
    person = get_object_or_404(
        User.objects.select_related("department", "team_lead"), pk=pk
    )
    today = timezone.localdate()
    first_day, last_day = payroll.month_bounds(today.year, today.month)
    return render(request, "hr/employee.html", {
        "person": person,
        "summary": (
            attendance.month_summary(person, first_day, last_day)
            if person.attendance_enabled else None
        ),
        "shifts": person.shifts.select_related("template").all(),
        "application": getattr(person, "candidate_record", None),
        "salary_records": person.salary_records.all()[:6],
        "probation_reviews": person.probation_reviews.all(),
        "leave_rows": person.leave_requests.all()[:6],
        "plans": SalaryPlan.objects.filter(is_active=True),
    })


@recruit_required
def hr_recruitment_settings(request):
    conf = RecruitmentSettings.load()
    form = RecruitmentSettingsForm(request.POST or None, instance=conf)
    if request.method == "POST" and form.is_valid():
        form.save()
        services.log(request.user, "recruitment.settings.update")
        flash.success(request, "اتحفظ")
        return redirect("dashboard:hr_recruitment_settings")

    return render(request, "hr/recruitment_settings.html", {
        "form": form,
        "conf": conf,
        "app": AppSettings.load(),
        "sample": recruitment.outbound_text(
            None, "مرحبًا من " + (conf.term_list[0] if conf.term_list else "—"), conf=conf
        ),
        "privacy_armed": bool(conf.term_list),
    })


# ---------------------------------------------------------------------------
# Leave, probation, performance, pay - sections 19, 20, 22, 23
# ---------------------------------------------------------------------------

@login_required
def my_leave(request):
    """Anybody's own leave: the balance, the history, and the form to ask."""
    person = request.user
    today = timezone.localdate()
    form = LeaveRequestForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            employees.request_leave(
                person,
                kind=form.cleaned_data["kind"],
                start_date=form.cleaned_data["start_date"],
                end_date=form.cleaned_data["end_date"],
                start_time=form.cleaned_data.get("start_time"),
                end_time=form.cleaned_data.get("end_time"),
                reason=form.cleaned_data.get("reason", ""),
                actor=person,
            )
        except employees.LifecycleError as refused:
            flash.error(request, refused.ar)
        else:
            flash.success(request, "الطلب اتبعت")
            return redirect("dashboard:my_leave")

    return render(request, "hr/my_leave.html", {
        "form": form,
        "balance": employees.leave_balance(person, today.year, today.month),
        "rows": person.leave_requests.all()[:40],
        "conf": PayrollSettings.load(),
    })


@hr_required
def hr_leave(request):
    """The queue. What somebody can do to a row depends on where it is."""
    rows = LeaveRequest.objects.select_related("user", "manager", "hr_decision_by")
    if request.GET.get("status"):
        rows = rows.filter(status=request.GET["status"])
    if request.GET.get("user"):
        rows = rows.filter(user_id=request.GET["user"])

    waiting = LeaveRequest.objects.filter(
        status__in=(LeaveStatus.PENDING, LeaveStatus.MANAGER_OK)
    ).select_related("user", "manager")
    return render(request, "hr/leave.html", {
        "waiting": waiting,
        "rows": rows[:200],
        "statuses": LeaveStatus.choices,
        "people": User.objects.filter(is_active=True),
        "selected": request.GET,
        "conf": PayrollSettings.load(),
        "form": LeaveDecisionForm(),
    })


@login_required
@require_POST
def leave_decide(request, pk, action):
    """Approve or reject. The manager's step and HR's step both land here."""
    row = get_object_or_404(LeaveRequest.objects.select_related("user"), pk=pk)
    try:
        employees.decide_leave(
            row, request.user, approve=(action == "approve"),
            note=request.POST.get("note", ""),
        )
    except employees.LifecycleError as refused:
        flash.error(request, refused.ar)
    else:
        flash.success(request, "اتسجل")
    return redirect(request.POST.get("next") or "dashboard:hr_leave")


@login_required
@require_POST
def leave_cancel(request, pk):
    """Withdrawing your own request, while nobody has acted on it."""
    row = get_object_or_404(LeaveRequest, pk=pk, user=request.user)
    if not row.is_open:
        flash.error(request, "الطلب اتقرر فيه بالفعل.")
    else:
        row.status = LeaveStatus.CANCELLED
        row.save(update_fields=["status"])
        services.log(request.user, "leave.cancel", str(pk))
        flash.success(request, "اتسحب")
    return redirect("dashboard:my_leave")


@hr_required
def hr_probation(request):
    """Section 19: who is on probation and which reviews have come due."""
    rows = ProbationReview.objects.select_related("user", "reviewer").filter(
        user__is_active=True
    )
    if request.GET.get("state") == "due":
        rows = rows.filter(
            outcome=ProbationOutcome.PENDING, due_date__lte=timezone.localdate()
        )
    elif request.GET.get("state") != "all":
        rows = rows.filter(outcome=ProbationOutcome.PENDING)

    return render(request, "hr/probation.html", {
        "rows": rows[:200],
        "form": ProbationDecisionForm(),
        "on_probation": User.objects.filter(
            is_active=True, employment_status=EmploymentStatus.PROBATION
        ).select_related("department"),
        "due_count": ProbationReview.objects.filter(
            outcome=ProbationOutcome.PENDING, due_date__lte=timezone.localdate(),
            user__is_active=True,
        ).count(),
        "selected": request.GET,
    })


@hr_required
@require_POST
def probation_decide(request, pk):
    review = get_object_or_404(ProbationReview.objects.select_related("user"), pk=pk)
    form = ProbationDecisionForm(request.POST)
    if not form.is_valid():
        flash.error(request, "الفورم مش مظبوط.")
        return redirect("dashboard:hr_probation")
    try:
        employees.decide_probation(
            review, request.user,
            outcome=form.cleaned_data["outcome"],
            score=form.cleaned_data.get("score"),
            notes=form.cleaned_data.get("notes", ""),
            extend_days=form.cleaned_data.get("extend_days") or 0,
        )
    except employees.LifecycleError as refused:
        flash.error(request, refused.ar)
    else:
        flash.success(request, "اتسجل")
    return redirect("dashboard:hr_probation")


@hr_required
@require_POST
def probation_open(request, pk):
    """Start the three reviews for somebody hired before this existed."""
    person = get_object_or_404(User, pk=pk)
    created = employees.open_probation(person, actor=request.user)
    flash.success(request, f"{len(created)} مراجعة اتفتحت")
    return redirect(request.POST.get("next") or "dashboard:hr_probation")


@recruit_required
def hr_performance(request):
    """Section 20, for one person and one month."""
    year, month = _requested_month(request)
    people = User.objects.filter(is_active=True, role=Role.TRANSLATOR)
    person_id = request.GET.get("user")
    person = people.filter(pk=person_id).first() if person_id else people.first()

    report = performance.for_month(person, year, month) if person else None
    if report:
        for key, part in report["parts"].items():
            part["band"] = performance.band(part.get("score"))
        report["band"] = performance.band(report["overall"])

    return render(request, "hr/performance.html", {
        "people": people,
        "person": person,
        "report": report,
        "year": year,
        "month": month,
        "periods": _period_choices(),
    })


@recruit_required
def hr_complaints(request):
    form = ClientComplaintForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        row.logged_by = request.user
        row.save()
        services.log(
            request.user, "complaint.log",
            row.translator.username if row.translator else "", row.summary[:80],
        )
        flash.success(request, "اتسجلت")
        return redirect("dashboard:hr_complaints")

    rows = ClientComplaint.objects.select_related("client", "task", "translator")
    if request.GET.get("translator"):
        rows = rows.filter(translator_id=request.GET["translator"])
    return render(request, "hr/complaints.html", {
        "form": form,
        "rows": rows[:150],
        "people": User.objects.filter(is_active=True, role=Role.TRANSLATOR),
        "selected": request.GET,
    })


@recruit_required
@require_POST
def complaint_resolve(request, pk):
    row = get_object_or_404(ClientComplaint, pk=pk)
    row.resolved = not row.resolved
    row.save(update_fields=["resolved"])
    services.log(request.user, "complaint.resolve", str(pk))
    return redirect("dashboard:hr_complaints")


@admin_only
def hr_salary_plans(request):
    """Section 23's plans. Owner-only: they move money."""
    editing = SalaryPlan.objects.filter(pk=request.GET.get("edit")).first()
    form = SalaryPlanForm(request.POST or None, instance=editing)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        if not row.pk:
            row.created_by = request.user
        row.save()
        services.log(request.user, "salary.plan.save", row.name)
        flash.success(request, "اتحفظت")
        return redirect("dashboard:hr_salary_plans")

    return render(request, "hr/salary_plans.html", {
        "form": form,
        "editing": editing,
        "rows": SalaryPlan.objects.all(),
        "conf": PayrollSettings.load(),
        "unassigned": User.objects.filter(
            is_active=True, role=Role.TRANSLATOR, salary_plan__isnull=True
        ).count(),
    })


@admin_only
@require_POST
def assign_salary_plan(request, pk):
    person = get_object_or_404(User, pk=pk)
    raw = request.POST.get("plan") or ""
    person.salary_plan = SalaryPlan.objects.filter(pk=raw).first() if raw else None
    person.save(update_fields=["salary_plan"])
    services.log(
        request.user, "salary.plan.assign", person.username,
        person.salary_plan.name if person.salary_plan else "company rules",
    )
    flash.success(request, "اتسجل")
    return redirect(request.POST.get("next") or "dashboard:hr_salary_plans")


@recruit_required
def hr_salary_requests(request):
    """HR asks here; the owner decides here. Nobody edits a salary directly."""
    people = User.objects.filter(is_active=True)
    person = people.filter(pk=request.GET.get("user")).first()
    form = SalaryChangeRequestForm(request.POST or None, initial={
        "effective_from": timezone.localdate(),
    })

    if request.method == "POST" and person is not None and form.is_valid():
        try:
            employees.request_salary_change(
                person,
                new_amount=form.cleaned_data["new_amount"],
                effective_from=form.cleaned_data["effective_from"],
                reason=form.cleaned_data.get("reason", ""),
                actor=request.user,
            )
        except employees.LifecycleError as refused:
            flash.error(request, refused.ar)
        else:
            flash.success(request, "الطلب اتبعت للمالك")
            return redirect("dashboard:hr_salary_requests")

    return render(request, "hr/salary_requests.html", {
        "form": form,
        "people": people,
        "person": person,
        "current": SalaryRecord.amount_on(person, timezone.localdate()) if person else None,
        "pending": SalaryChangeRequest.objects.filter(
            status=ApprovalStatus.PENDING
        ).select_related("user", "requested_by"),
        "decided": SalaryChangeRequest.objects.exclude(
            status=ApprovalStatus.PENDING
        ).select_related("user", "decided_by")[:40],
    })


@owner_required
@require_POST
def salary_request_decide(request, pk, action):
    row = get_object_or_404(SalaryChangeRequest.objects.select_related("user"), pk=pk)
    try:
        employees.decide_salary_change(
            row, request.user, approve=(action == "approve"),
            note=request.POST.get("note", ""),
        )
    except employees.LifecycleError as refused:
        flash.error(request, refused.ar)
    else:
        flash.success(request, "اتسجل القرار")
    return redirect("dashboard:hr_salary_requests")
