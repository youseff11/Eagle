# Run the tests you care about, fast. From D:\Progects\Eagle\Core:
#
#   .\t.ps1                              كل التستات (سريع)
#   .\t.ps1 ActionsFollowTheFilesTests   كلاس واحد
#   .\t.ps1 ActionsFollowTheFilesTests.test_a_message_that_is_only_words_gets_none
#   .\t.ps1 -All                         بالإعدادات الحقيقية، زي ما السيرفر هيشغلها
#
# The fast path skips the migrations and runs on an in-memory database - see
# Core/settings_test.py for what that hides. Use -All before you push.

param(
    [string]$What = "dashboard",
    [switch]$All
)

if ($What -ne "dashboard" -and $What -notlike "dashboard.*") {
    $What = "dashboard.tests.$What"
}

if ($All) {
    python manage.py test $What
    python manage.py makemigrations --check --dry-run
} else {
    python manage.py test $What --settings=Core.settings_test --failfast
}
