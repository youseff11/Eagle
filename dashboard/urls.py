"""URL map for the Eagle dashboard app."""

from django.urls import path

from . import api, views, webhooks

app_name = "dashboard"

urlpatterns = [
    # -- auth ---------------------------------------------------------------
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.home, name="home"),

    # -- operation ----------------------------------------------------------
    path("ops/inbox/", views.ops_inbox, name="ops_inbox"),
    path("ops/tasks/", views.ops_tasks, name="ops_tasks"),
    path("ops/tasks/new/", views.ops_task_new, name="ops_task_new"),
    path("ops/team/", views.ops_team, name="ops_team"),

    # -- team leader / translator -------------------------------------------
    path("lead/", views.lead_home, name="lead_home"),
    path("translator/", views.translator_home, name="translator_home"),

    # -- tasks --------------------------------------------------------------
    path("tasks/<str:code>/", views.task_detail, name="task_detail"),
    path("tasks/<str:code>/requirement/", views.task_add_requirement, name="task_requirement"),

    # -- clients ------------------------------------------------------------
    path("clients/", views.client_list, name="client_list"),
    path("clients/<str:code>/", views.client_detail, name="client_detail"),

    # -- notifications ------------------------------------------------------
    path("notifications/", views.notifications, name="notifications"),

    # -- admin panel --------------------------------------------------------
    path("panel/", views.admin_overview, name="admin_overview"),
    path("panel/settings/", views.admin_settings, name="admin_settings"),
    path("panel/users/", views.admin_users, name="admin_users"),
    path("panel/users/new/", views.admin_user_new, name="admin_user_new"),
    path("panel/users/<int:pk>/", views.admin_user_edit, name="admin_user_edit"),
    path("panel/users/<int:pk>/shifts/add/", views.admin_shift_add, name="admin_shift_add"),
    path(
        "panel/users/<int:pk>/shifts/<int:shift_id>/delete/",
        views.admin_shift_delete,
        name="admin_shift_delete",
    ),
    path("panel/clients/", views.admin_clients, name="admin_clients"),
    path("panel/clients/new/", views.client_form, name="admin_client_new"),
    path("panel/clients/<str:code>/edit/", views.client_form, name="admin_client_edit"),
    path("panel/simulate/", views.admin_simulate, name="admin_simulate"),
    path("panel/audit/", views.admin_audit, name="admin_audit"),

    # -- json api -----------------------------------------------------------
    path("api/heartbeat/", api.heartbeat, name="api_heartbeat"),
    path("api/notifications/read/", api.mark_notifications_read, name="api_notifications_read"),
    path("api/prefs/", api.set_prefs, name="api_prefs"),
    path("api/assignments/<int:pk>/accept/", api.accept_assignment, name="api_accept"),
    path("api/assignments/<int:pk>/decline/", api.decline_assignment, name="api_decline"),
    path("api/tasks/<str:code>/assign-lead/", api.assign_lead, name="api_assign_lead"),
    path(
        "api/tasks/<str:code>/assign-translator/",
        api.assign_translator,
        name="api_assign_translator",
    ),
    path("api/tasks/<str:code>/deadline/", api.set_deadline, name="api_set_deadline"),
    path("api/tasks/<str:code>/ai-check/", api.ai_check, name="api_ai_check"),
    path("api/tasks/<str:code>/<str:action>/", api.task_action, name="api_task_action"),
    path("api/messages/<int:pk>/claim/", api.claim_message, name="api_claim_message"),
    path("api/rooms/<int:room_id>/messages/", api.chat_fetch, name="api_chat_fetch"),
    path("api/rooms/<int:room_id>/send/", api.chat_send, name="api_chat_send"),
    path("api/clients/<str:client_code>/requirement/", api.add_requirement, name="api_requirement"),

    # -- webhooks -----------------------------------------------------------
    path("webhooks/whatsapp/", webhooks.whatsapp, name="wh_whatsapp"),
    path("webhooks/email/", webhooks.email_hook, name="wh_email"),
]
