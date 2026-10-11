#!/usr/bin/env python
"""Eagle's verification gate - the loop closes here, not in a person's head.

Every check below exists because that exact mistake was made on this project
once already, and cost real time. Run it before saying a change is done:

    python .claude/verify.py          everything, tests included
    python .claude/verify.py --fast   static checks only, no tests

Exit code 0 means the tree is green. Anything else means stop and read.

Standard library only, on purpose: this has to run even when the environment
is half-built. The checks that need Django shell out to manage.py, so a
missing Django is reported as a skip - never a crash, and never a silent pass.

A note is not a failure. Notes are things worth a look that the project has
decided are acceptable.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git", ".claude", "claude-setup", "staticfiles", "media", "__pycache__",
    "node_modules", ".venv", "venv", "env", "ENV", ".test-media",
    "Claude outputs", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
CODE_SUFFIXES = (".py", ".html", ".css", ".js")
# The React app is TypeScript: the no-emoji rule applies to it the same way.
TEXT_SUFFIXES = CODE_SUFFIXES + (".ts", ".tsx")

# Emoji, and nothing else. The codebase leans on typographic characters that
# are NOT emoji and must never be flagged: em dash, middle dot, guillemets,
# arrows, ellipsis, multiplication and division signs.
EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),   # pictographs, faces, flags, symbols
    (0x2600, 0x27BF),     # miscellaneous symbols + dingbats
    (0x2B00, 0x2BFF),     # arrows drawn as emoji
    (0x2934, 0x2935),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3299),
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0xFE0F, 0xFE0F),     # variation selector: turns a glyph into an emoji
)

# Invisible characters that render as nothing and break things that parse.
INVISIBLE = {
    0x200B: "zero width space",
    0x200E: "left-to-right mark",
    0x200F: "right-to-left mark",
    0x2028: "line separator",
    0x2029: "paragraph separator",
    0x00A0: "non-breaking space",
    0xFEFF: "byte order mark",
}

# Tags that wrap content and need a matching end tag.
PAIRED_TAGS = {
    "if": "endif",
    "for": "endfor",
    "with": "endwith",
    "block": "endblock",
    "comment": "endcomment",
    "verbatim": "endverbatim",
    "spaceless": "endspaceless",
    "autoescape": "endautoescape",
    "filter": "endfilter",
    "ifchanged": "endifchanged",
    "blocktrans": "endblocktrans",
    "blocktranslate": "endblocktranslate",
    "cache": "endcache",
    "localize": "endlocalize",
}
# Tags that live inside a paired tag and open nothing of their own.
BRANCH_TAGS = {"else", "elif", "empty", "plural"}

# Django's own lexer regex. No DOTALL - that is the whole point of one check.
TAG_RE = re.compile(r"({%.*?%}|{{.*?}}|{#.*?#})")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def walk(suffixes=CODE_SUFFIXES):
    """Every source file in the repo, skipping the generated and the vendored."""
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def lines(text):
    """Split on newlines and nothing else.

    str.splitlines() also breaks on U+2028 and U+2085, which would hide the
    very characters one of the checks below is looking for - and would shift
    every line number away from what the editor shows.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def rel(path):
    return path.relative_to(ROOT).as_posix()


def run(args, timeout=900, env=None):
    """Run a manage.py command. Returns (ok, combined output, django_missing)."""
    try:
        proc = subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            env={**os.environ, **(env or {})},
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s", False
    output = (proc.stdout or "") + (proc.stderr or "")
    missing = "No module named 'django'" in output or "ModuleNotFoundError" in output
    return proc.returncode == 0, output.strip(), missing


def tail(text, lines=25):
    rows = [r for r in text.split("\n") if r.strip()]
    return "\n".join(rows[-lines:])


# --------------------------------------------------------------------------
# checks - each returns (failures, notes)
# --------------------------------------------------------------------------

def check_no_emoji():
    """Project rule: zero emoji in code, comments included.

    A rule, not a taste: the dashboard is bilingual and emoji render
    differently on every platform the team uses.
    """
    failures = []
    for path in walk(TEXT_SUFFIXES):
        for number, line in enumerate(lines(read(path)), 1):
            for char in line:
                code = ord(char)
                if any(low <= code <= high for low, high in EMOJI_RANGES):
                    failures.append(
                        f"{rel(path)}:{number} emoji U+{code:04X} - remove it"
                    )
                    break
    return failures, []


def check_invisible_characters():
    """Characters that render as nothing and break whatever parses them.

    A U+2028 inside a Python string is invisible in the editor and a syntax
    error the day that string reaches a JavaScript literal.
    """
    notes = []
    for path in walk(TEXT_SUFFIXES):
        for number, line in enumerate(lines(read(path)), 1):
            for char in line:
                if ord(char) in INVISIBLE:
                    notes.append(
                        f"{rel(path)}:{number} {INVISIBLE[ord(char)]} "
                        f"(U+{ord(char):04X}) - invisible, check it is meant"
                    )
                    break
    return [], notes


def eagle_tag_names():
    """Every tag and filter eagle_tags registers, read from the file itself."""
    source = ROOT / "dashboard" / "templatetags" / "eagle_tags.py"
    if not source.exists():
        return set()
    names = set()
    source_lines = lines(read(source))
    for index, line in enumerate(source_lines):
        if not line.strip().startswith("@register."):
            continue
        for following in source_lines[index + 1:index + 4]:
            match = re.match(r"\s*def\s+(\w+)", following)
            if match:
                names.add(match.group(1))
                break
    return names


def check_load_eagle_tags():
    """{% load %} is not inherited through {% extends %} or {% include %}.

    This one returned 500 on /privacy/ in production.
    """
    names = eagle_tag_names()
    if not names:
        return [], ["eagle_tags.py not found - load check skipped"]
    failures = []
    load_re = re.compile(r"{%-?\s*load\s+([^%]*?)-?%}")
    for path in walk((".html",)):
        text = read(path)
        # "{% load static eagle_tags %}" is the common spelling here, so read
        # the library list rather than matching one exact string.
        loaded = set()
        for group in load_re.findall(text):
            loaded.update(group.split())
        if "eagle_tags" in loaded:
            continue
        used = set()
        for name in names:
            if re.search(r"{%-?\s*" + name + r"[\s%]", text):
                used.add(name)
            if re.search(r"\|\s*" + name + r"[\s:|}]", text):
                used.add(name)
        if used:
            failures.append(
                f"{rel(path)} uses {', '.join(sorted(used))} "
                f"without {{% load eagle_tags %}}"
            )
    return failures, []


def check_single_line_comments():
    """{# #} must open and close on one line.

    Django's lexer regex has no DOTALL, so a comment spanning two lines is not
    a comment at all: it renders as text, and any {% %} inside it executes.
    This returned 500 on /attendance/.
    """
    failures = []
    for path in walk((".html",)):
        for number, line in enumerate(lines(read(path)), 1):
            if line.count("{#") != line.count("#}"):
                failures.append(
                    f"{rel(path)}:{number} {{# #}} spans lines - "
                    f"use {{% comment %}} instead"
                )
    return failures, []


def check_template_tags_balance():
    """Every {% if %} closed, and closed by the right end tag."""
    failures = []
    for path in walk((".html",)):
        stack = []
        skip_until = None
        for piece in TAG_RE.findall(read(path)):
            if not piece.startswith("{%"):
                continue
            body = piece[2:-2].strip().lstrip("-").strip()
            if not body:
                continue
            name = body.split()[0]
            # Django swallows what is inside these two whole, so must we.
            if skip_until:
                if name == skip_until:
                    skip_until = None
                continue
            if name in ("comment", "verbatim"):
                skip_until = PAIRED_TAGS[name]
                continue
            if name in BRANCH_TAGS:
                continue
            if name in PAIRED_TAGS:
                stack.append(name)
            elif name in PAIRED_TAGS.values():
                if not stack:
                    failures.append(f"{rel(path)} stray {{% {name} %}}")
                elif PAIRED_TAGS[stack[-1]] != name:
                    failures.append(
                        f"{rel(path)} {{% {name} %}} closes {{% {stack[-1]} %}}"
                    )
                    stack.pop()
                else:
                    stack.pop()
        if skip_until:
            failures.append(f"{rel(path)} unclosed {{% {skip_until[3:]} %}}")
        for name in stack:
            failures.append(f"{rel(path)} unclosed {{% {name} %}}")
    return failures, []


def check_icon_names():
    """An icon name missing from the sprite renders an empty SVG and no error.

    Nothing anywhere says the name was wrong - the icon is simply not there.
    """
    sprite = ROOT / "templates" / "partials" / "icons.html"
    if not sprite.exists():
        return [], ["icons.html not found - icon check skipped"]
    known = set(re.findall(r'id="i-([\w-]+)"', read(sprite)))
    failures = []
    for path in walk((".html",)):
        for number, line in enumerate(lines(read(path)), 1):
            for name in re.findall(r'{%-?\s*icon\s+"([\w-]+)"', line):
                if name not in known:
                    failures.append(
                        f"{rel(path)}:{number} icon \"{name}\" is not in the sprite"
                    )
    # The same name built in JavaScript, where a typo is just as silent.
    for path in walk((".js",)):
        for number, line in enumerate(lines(read(path)), 1):
            for name in re.findall(r'icon\(\s*"([\w-]+)"', line):
                if name not in known:
                    failures.append(
                        f"{rel(path)}:{number} icon(\"{name}\") is not in the sprite"
                    )
    return failures, []


def check_conventions():
    """The three names that get typed wrong because they sound right."""
    failures = []
    for path in walk((".html", ".css", ".js")):
        for number, line in enumerate(lines(read(path)), 1):
            where = f"{rel(path)}:{number}"
            if re.search(r"var\(\s*--line\b", line) or re.search(r"^\s*--line\s*:", line):
                failures.append(f"{where} the variable is --border, not --line")
            if "ic--xs" in line:
                failures.append(f"{where} there is no ic--xs - sizes are sm/lg/xl")
            if re.search(r'{%-?\s*icon\s+"chat"', line) or re.search(r'icon\(\s*"chat"', line):
                failures.append(f"{where} there is no chat icon - use message")
    return failures, []


def check_url_names():
    """Every {% url 'dashboard:x' %} and reverse() points at a real name."""
    urls = ROOT / "dashboard" / "urls.py"
    if not urls.exists():
        return [], ["urls.py not found - url check skipped"]
    known = set(re.findall(r'name="([\w_]+)"', read(urls)))
    known |= set(re.findall(r"name='([\w_]+)'", read(urls)))
    # The classic interface's old names live in legacy.py's table: ("old/address/", "url_name", "/app/target", ...).
    legacy = ROOT / "dashboard" / "legacy.py"
    if legacy.exists():
        known |= set(re.findall(r'\(\s*"[^"]+",\s*"([\w_]+)",\s*"/', read(legacy)))
    failures = []
    pattern = re.compile(r"""dashboard:([\w_]+)""")
    for path in walk((".html", ".py")):
        if path == urls:
            continue
        for number, line in enumerate(lines(read(path)), 1):
            for name in pattern.findall(line):
                if name not in known:
                    failures.append(
                        f"{rel(path)}:{number} dashboard:{name} is not in urls.py"
                    )
    return failures, []


def check_duplicate_ids():
    """Two elements sharing an id is how initChat() grabbed the wrong one.

    A note, not a failure: some of these are deliberate - the same id in two
    templates that never render together.
    """
    seen = {}
    for path in walk((".html",)):
        for number, line in enumerate(lines(read(path)), 1):
            for element_id in re.findall(r'\sid="([\w-]+)"', line):
                seen.setdefault(element_id, []).append(f"{rel(path)}:{number}")
    notes = []
    for element_id, places in sorted(seen.items()):
        if len(places) > 1:
            notes.append(f'id="{element_id}" in {len(places)} places: {", ".join(places[:4])}')
    return [], notes


def check_git_clean():
    """Secrets and client files must not be tracked. db.sqlite3 holds tokens."""
    try:
        proc = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return [], [f"git not available - tracking check skipped ({error})"]
    if proc.returncode != 0:
        return [], ["not a git repository - tracking check skipped"]
    tracked = proc.stdout.splitlines()
    failures = []
    for name in tracked:
        lowered = name.lower()
        if lowered.endswith(".sqlite3"):
            failures.append(f"{name} is tracked - it holds the WhatsApp token")
        elif lowered == ".env" or lowered.startswith(".env."):
            if not lowered.endswith(".example"):
                failures.append(f"{name} is tracked - secrets")
        elif lowered.startswith("media/") and not lowered.endswith(".gitkeep"):
            failures.append(f"{name} is tracked - client files belong in media/ only")
    return failures, []


def check_django(fast):
    """Django's own checks, the migration state, and the test suite."""
    failures, notes = [], []

    ok, output, missing = run(["check"])
    if missing:
        return [], ["Django is not importable here - manage.py checks skipped"]
    if not ok:
        failures.append("manage.py check failed:\n" + tail(output))

    if fast:
        notes.append("--fast: migrations and tests were not run")
        return failures, notes

    ok, output, _ = run(["makemigrations", "--check", "--dry-run"])
    if not ok:
        failures.append(
            "models.py and the migrations disagree. Compare the definition, "
            "not just the presence - choices and help_text count:\n" + tail(output)
        )

    # Real migrations replayed, cheap password hasher. The production hasher
    # costs ~600 ms per user and made this step a 24-minute run that the 900 s
    # timeout then reported as "red" - a gate nobody can pass is not a gate.
    #
    # One worker per core (2026-10-11: 98 s instead of 255 s). A failing test
    # under --parallel can take Django's runner down with it ("cannot pickle
    # 'traceback' object" - the fix is the tblib package, and Django is the
    # only dependency), so the run is red but does not say which test. Red is
    # therefore run again one test after another, which names the failures.
    suite = ["test", "dashboard", "--settings=Core.settings_test"]
    replay = {"EAGLE_REPLAY_MIGRATIONS": "1"}
    ok, output, _ = run([*suite, "--parallel", "auto"], env=replay)
    if not ok:
        ok, output, _ = run(suite, env=replay)
        if ok:
            failures.append(
                "the test suite is red when the tests run side by side and green "
                "one after another: tests that share state, or a flaky one. "
                "Run: python manage.py test dashboard --settings=Core.settings_test --parallel auto"
            )
        else:
            # Every red test by name first: the tail below only reaches the last one.
            named = [row for row in output.split("\n") if row.startswith(("FAIL:", "ERROR:"))]
            failures.append("the test suite is red:\n" + "\n".join(named[:30]) + "\n\n" + tail(output, 40))

    return failures, notes


def check_frontend(fast):
    """The React app's own tests and its build (type check included).

    From phase 5 the front end carries tests that pin what a role may see, so a
    gate that never ran them could stay green while a screen leaked. Not run
    with --fast. A machine without npm reports a skip as a note; a machine with
    npm but no installed packages fails, because a green gate that did not look
    is the one thing this file must not be.
    """
    app = ROOT / "frontend"
    if not (app / "package.json").exists():
        return [], ["frontend/ not found - front end checks skipped"]
    if fast:
        return [], ["--fast: front end tests and build were not run"]
    npm = shutil.which("npm")
    if npm is None:
        return [], ["npm is not installed here - front end tests and build were not run"]
    if not (app / "node_modules").is_dir():
        return ["frontend/node_modules is missing - run: cd frontend && npm ci"], []
    failures = []
    for script in ("test", "build"):
        try:
            proc = subprocess.run(
                [npm, "run", script], cwd=app, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600,
                env={**os.environ, "CI": "1"},
            )
        except subprocess.TimeoutExpired:
            failures.append(f"npm run {script} timed out after 600s")
            continue
        if proc.returncode != 0:
            failures.append(
                f"npm run {script} failed:\n" + tail((proc.stdout or "") + (proc.stderr or ""), 40)
            )
    return failures, []


CHECKS = [
    ("no emoji in code", check_no_emoji),
    ("invisible characters", check_invisible_characters),
    ("{% load eagle_tags %}", check_load_eagle_tags),
    ("{# #} on one line", check_single_line_comments),
    ("template tags balance", check_template_tags_balance),
    ("icon names exist", check_icon_names),
    ("naming conventions", check_conventions),
    ("url names exist", check_url_names),
    ("duplicate element ids", check_duplicate_ids),
    ("git tracking", check_git_clean),
]


def main():
    parser = argparse.ArgumentParser(description="Eagle's verification gate.")
    parser.add_argument(
        "--fast", action="store_true",
        help="static checks only - no migrations check and no tests",
    )
    args = parser.parse_args()
    # The failures carry the tests' own output (Arabic, arrows): a Windows
    # console in cp1252 raised UnicodeEncodeError on them, and the gate died
    # without saying what was red.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    all_failures, all_notes = [], []

    for title, check in CHECKS:
        failures, notes = check()
        all_failures.extend(failures)
        all_notes.extend(notes)
        mark = "FAIL" if failures else "ok  "
        print(f"[{mark}] {title}")

    # One after the other, each with every core. Side by side (tried
    # 2026-10-11) was no faster - both are CPU-bound on the same cores - and
    # the front end's tests ran past their 5 s limit: red for nothing.
    for title, check in (("django, migrations, tests", check_django), ("front end tests and build", check_frontend)):
        failures, notes = check(args.fast)
        all_failures.extend(failures)
        all_notes.extend(notes)
        print(f"[{'FAIL' if failures else 'ok  '}] {title}", flush=True)

    if all_notes:
        print("\nNotes (not failures):")
        for note in all_notes[:40]:
            print(f"  - {note}")
        if len(all_notes) > 40:
            print(f"  ... and {len(all_notes) - 40} more")

    if all_failures:
        print(f"\n{len(all_failures)} problem(s):\n")
        for failure in all_failures:
            print(f"  * {failure}")
        print("\nNot done. Fix these, then run it again.")
        return 1

    print("\nGreen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
