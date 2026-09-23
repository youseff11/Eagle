"""URL map for the Eagle dashboard app."""

from django.urls import path

from . import api, views, webhooks

app_name = "dashboard"

urlpatterns = [
    # -- auth ---------------------------------------------------------------
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.home, name="home"),

    # -- public legal pages (no login) --------------------------------------
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("data-deletion/", views.data_deletion, name="data_deletion"),

    # -- operation ----------------------------------------------------------
    path("ops/inbox/", views.ops_inbox, name="ops_inbox"),
    path("ops/inbox/thread/<int:pk>/", views.ops_mail_thread, name="ops_mail_thread"),
    path("ops/chats/", views.ops_chats, name="ops_chats"),
    path("ops/chats/g/<int:room_id>/", views.ops_group_chat, name="ops_group_chat"),
    # Before the client-code route: "u" would otherwise read as a client code.
    path("ops/chats/u/<int:user_id>/", views.ops_staff_chat, name="ops_staff_chat"),
    path("ops/chats/<str:code>/", views.ops_chats, name="ops_chat_detail"),
    path("ops/tasks/", views.ops_tasks, name="ops_tasks"),
    path("ops/tasks/new/", views.ops_task_new, name="ops_task_new"),
    path("ops/team/", views.ops_team, name="ops_team"),

    # -- team leader / translator -------------------------------------------
    path("lead/", views.lead_home, name="lead_home"),
    path("lead/translators/", views.lead_translators, name="lead_translators"),
    path("translator/", views.translator_home, name="translator_home"),
    path("translator/payroll/", views.translator_payroll, name="translator_payroll"),

    # -- accounts -----------------------------------------------------------
    path("accounts/", views.accounts_overview, name="accounts_overview"),
    path("accounts/recalculate/", views.accounts_recalculate, name="accounts_recalculate"),
    path(
        "accounts/period/<int:pk>/approve/",
        views.accounts_period_approve,
        name="accounts_period_approve",
    ),
    path("accounts/line/<int:pk>/", views.accounts_line, name="accounts_line"),
    path(
        "accounts/line/<int:pk>/bonus/",
        views.accounts_line_bonus,
        name="accounts_line_bonus",
    ),
    path("accounts/attendance/", views.accounts_attendance, name="accounts_attendance"),
    path("accounts/violations/", views.accounts_violations, name="accounts_violations"),
    path(
        "accounts/violations/<int:pk>/<str:action>/",
        views.accounts_violation_decide,
        name="accounts_violation_decide",
    ),
    path("accounts/rules/", views.accounts_rules, name="accounts_rules"),
    path("accounts/rules/tier/", views.accounts_tier_add, name="accounts_tier_add"),
    path(
        "accounts/rules/tier/<int:pk>/delete/",
        views.accounts_tier_delete,
        name="accounts_tier_delete",
    ),
    path("accounts/salary/<int:pk>/", views.accounts_salary, name="accounts_salary"),

    # -- attendance: the person's own card ----------------------------------
    path("attendance/", views.my_attendance, name="my_attendance"),

    # -- attendance: HR -----------------------------------------------------
    path("hr/attendance/", views.hr_attendance, name="hr_attendance"),
    path("hr/attendance/<int:pk>/", views.hr_attendance_day, name="hr_attendance_day"),
    path(
        "hr/attendance/<int:pk>/clear/",
        views.hr_attendance_clear,
        name="hr_attendance_clear",
    ),
    path("hr/report/", views.hr_report, name="hr_report"),
    path("hr/schedules/", views.hr_schedules, name="hr_schedules"),
    path("hr/schedules/shift/<int:pk>/delete/", views.hr_shift_delete, name="hr_shift_delete"),
    path(
        "hr/schedules/override/<int:pk>/delete/",
        views.hr_override_delete,
        name="hr_override_delete",
    ),
    path("hr/schedules/template/", views.hr_template_add, name="hr_template_add"),
    path("hr/offices/", views.hr_offices, name="hr_offices"),
    path("hr/offices/<int:pk>/delete/", views.hr_office_delete, name="hr_office_delete"),
    path("hr/devices/", views.hr_devices, name="hr_devices"),
    path("hr/devices/<int:pk>/<str:action>/", views.hr_device_decide, name="hr_device_decide"),
    path("hr/overtime/", views.hr_overtime, name="hr_overtime"),
    path(
        "hr/overtime/<int:pk>/<str:action>/",
        views.hr_overtime_decide,
        name="hr_overtime_decide",
    ),

    # -- HR / recruitment ---------------------------------------------------
    path("hr/recruitment/", views.hr_recruitment, name="hr_recruitment"),
    path("hr/recruitment/settings/", views.hr_recruitment_settings, name="hr_recruitment_settings"),
    path("hr/vacancies/", views.hr_vacancies, name="hr_vacancies"),
    path("hr/vacancies/<str:code>/", views.hr_vacancy, name="hr_vacancy"),
    path(
        "hr/vacancies/question/<int:pk>/delete/",
        views.hr_vacancy_question_delete,
        name="hr_vacancy_question_delete",
    ),
    path("hr/questions/", views.hr_questions, name="hr_questions"),
    path("hr/departments/", views.hr_department_add, name="hr_department_add"),
    path("hr/candidates/", views.hr_candidates, name="hr_candidates"),
    path("hr/candidates/<str:code>/", views.hr_candidate, name="hr_candidate"),
    path("hr/candidates/<str:code>/hire/", views.hr_hire, name="hr_hire"),
    path("hr/interviews/<int:pk>/score/", views.hr_interview_score, name="hr_interview_score"),
    path("hr/tests/<int:pk>/score/", views.hr_test_score, name="hr_test_score"),
    path("reviewer/tests/", views.reviewer_tests, name="reviewer_tests"),
    path("hr/approvals/", views.hr_approvals, name="hr_approvals"),
    path(
        "hr/approvals/<str:code>/<str:action>/",
        views.hr_approval_decide,
        name="hr_approval_decide",
    ),
    path("hr/employees/", views.hr_employees, name="hr_employees"),
    path("hr/employees/<int:pk>/", views.hr_employee, name="hr_employee"),

    # -- leave, probation, performance, pay ---------------------------------
    path("leave/", views.my_leave, name="my_leave"),
    path("leave/<int:pk>/cancel/", views.leave_cancel, name="leave_cancel"),
    path("hr/leave/", views.hr_leave, name="hr_leave"),
    path("hr/leave/<int:pk>/<str:action>/", views.leave_decide, name="leave_decide"),
    path("hr/probation/", views.hr_probation, name="hr_probation"),
    path("hr/probation/<int:pk>/decide/", views.probation_decide, name="probation_decide"),
    path("hr/probation/open/<int:pk>/", views.probation_open, name="probation_open"),
    path("hr/performance/", views.hr_performance, name="hr_performance"),
    path("hr/complaints/", views.hr_complaints, name="hr_complaints"),
    path("hr/complaints/<int:pk>/resolve/", views.complaint_resolve, name="complaint_resolve"),
    path("hr/salary-plans/", views.hr_salary_plans, name="hr_salary_plans"),
    path("hr/salary-plans/assign/<int:pk>/", views.assign_salary_plan, name="assign_salary_plan"),
    path("hr/salary-requests/", views.hr_salary_requests, name="hr_salary_requests"),
    path(
        "hr/salary-requests/<int:pk>/<str:action>/",
        views.salary_request_decide,
        name="salary_request_decide",
    ),

    # -- tasks --------------------------------------------------------------
    path("tasks/<str:code>/", views.task_detail, name="task_detail"),
    path("tasks/<str:code>/requirement/", views.task_add_requirement, name="task_requirement"),
    path("tasks/<str:code>/words/", views.task_word_count, name="task_word_count"),

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
    path("panel/reset-tasks/", views.admin_reset_tasks, name="admin_reset_tasks"),

    # -- json api -----------------------------------------------------------
    path("api/heartbeat/", api.heartbeat, name="api_heartbeat"),
    path("api/attendance/state/", api.attendance_state, name="api_attendance_state"),
    path("api/attendance/punch/", api.attendance_punch, name="api_attendance_punch"),
    path("api/notifications/read/", api.mark_notifications_read, name="api_notifications_read"),
    path("api/prefs/", api.set_prefs, name="api_prefs"),
    path("api/assignments/<int:pk>/accept/", api.accept_assignment, name="api_accept"),
    path("api/assignments/<int:pk>/decline/", api.decline_assignment, name="api_decline"),
    path(
        "api/assignments/<int:pk>/files/",
        api.open_assignment_files, name="api_assignment_files",
    ),
    path("api/tasks/<str:code>/assign-lead/", api.assign_lead, name="api_assign_lead"),
    path(
        "api/tasks/<str:code>/assign-translator/",
        api.assign_translator,
        name="api_assign_translator",
    ),
    path("api/tasks/<str:code>/deadline/", api.set_deadline, name="api_set_deadline"),
    path(
        "api/tasks/<str:code>/translator-deadline/",
        api.set_translator_deadline,
        name="api_set_translator_deadline",
    ),
    path("api/tasks/<str:code>/ai-check/", api.ai_check, name="api_ai_check"),
    path("api/tasks/<str:code>/deliver/", api.deliver, name="api_deliver"),
    path("api/integrations/whatsapp/test/", api.whatsapp_test, name="api_whatsapp_test"),
    path("api/integrations/email/test/", api.email_test, name="api_email_test"),
    path("api/tasks/<str:code>/<str:action>/", api.task_action, name="api_task_action"),
    path("api/inbox/feed/", api.inbox_feed, name="api_inbox_feed"),
    path("api/inbox/thread/<int:pk>/feed/", api.mail_thread_feed, name="api_mail_thread_feed"),
    path("api/inbox/thread/<int:pk>/reply/", api.mail_reply, name="api_mail_reply"),
    path("api/messages/<int:pk>/claim/", api.claim_message, name="api_claim_message"),
    path("api/messages/<int:pk>/confirm/", api.confirm_message, name="api_confirm_message"),
    path("api/mail/fetch/", api.fetch_mail, name="api_fetch_mail"),
    path("api/rooms/<int:room_id>/messages/", api.chat_fetch, name="api_chat_fetch"),
    path("api/rooms/<int:room_id>/send/", api.chat_send, name="api_chat_send"),
    path("api/clients/<str:client_code>/requirement/", api.add_requirement, name="api_requirement"),
    path("api/presence/", api.presence, name="api_presence"),
    path("api/client-chats/", api.client_chat_list, name="api_client_chat_list"),
    path("api/chats/forward/", api.chat_forward, name="api_chat_forward"),
    path("api/search/tasks/", api.search_tasks, name="api_search_tasks"),
    # Before the "<int:room_id>" routes: "team" is not a room id.
    path("api/groups/team/new/", api.team_group_create, name="api_team_group_create"),
    path("api/groups/<int:room_id>/", api.group_chat_fetch, name="api_group_chat_fetch"),
    path("api/groups/<int:room_id>/members/", api.group_add_members, name="api_group_add_members"),
    path("api/groups/<int:room_id>/send/", api.group_chat_send, name="api_group_chat_send"),
    path("api/client-chats/<str:client_code>/", api.client_chat_fetch, name="api_client_chat_fetch"),
    path(
        "api/client-chats/<str:client_code>/send/",
        api.client_chat_send,
        name="api_client_chat_send",
    ),

    # -- webhooks -----------------------------------------------------------
    path("webhooks/whatsapp/", webhooks.whatsapp_hook, name="wh_whatsapp"),
    path("webhooks/email/", webhooks.email_hook, name="wh_email"),
]
