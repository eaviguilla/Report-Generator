"""Pick the unittest targets a change needs, in three tiers, and optionally run them.

    .venv/bin/python scripts/relevant_tests.py              # iterate: only the tests you added or changed
    .venv/bin/python scripts/relevant_tests.py --affected   # before calling it done: what the change can reach
    .venv/bin/python scripts/relevant_tests.py --full       # everything; only when the user asked for it
    add --run to execute them; browser tests then run in parallel chunks

"Changed" means the working tree against HEAD, untracked files included. The same rules are written
out for people and assistants in .github/copilot-instructions.md, "Running tests in this repo".
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROWSER = "tests/test_browser.py"
REPORT_PAGES = frozenset({"setup", "findings", "content"})
ALL_PAGES = REPORT_PAGES | {"home"}
CLASS_WIDE = {"setUp", "tearDown", "setUpClass", "tearDownClass"}

# Where a browser test goes, read from its source and the helpers it calls. Clicks count too, because
# several tests reach their page through Next/Previous rather than a URL.
PAGE_PATTERNS = [
    (re.compile(r'/edit["?]|"Next: Content"'), "content"),
    (re.compile(r'/findings["?]|"(?:Next|Previous): Findings"|#finding-validation-note'), "findings"),
    (re.compile(r'/setup["?]|/new"|/reports/\{\w+\}"|"Previous: Setup"|"Open Setup"|report-name'), "setup"),
    (re.compile(r'\{self\.base_url\}/"'), "home"),
]
FEATURE_PATTERNS = [
    (re.compile(r"importable_docx|/reports/import|import-report|import-command"), "import"),
    (re.compile(r'/generate|name="Generate Report"'), "generate"),
]

# --affected: which browser tests a changed file can reach. Checked in order; the first match wins.
NO_TESTS = ("docs/", ".github/", ".claude/", "graphify-out/")
# The Claude rules in .claude/rules/ are generated from .github/instructions/, so a change to either side
# runs the one test that compares them, even though both folders otherwise select nothing.
RULE_COPIES = (".github/instructions/", ".claude/rules/")
RULE_SYNC_TEST = "tests.test_ai_rules_sync"
FILE_PAGES: list[tuple[str, frozenset[str]]] = [
    ("app/web/static/manager.js", frozenset({"home"})),
    ("app/web/static/save.js", REPORT_PAGES),  # the save code, loaded by Setup, Findings and Content only
    ("app/web/static/", ALL_PAGES),  # dialog.js, theme.js, diagnostics.js and every stylesheet load everywhere
    ("app/web/templates/page1_setup.html", frozenset({"setup"})),
    ("app/web/templates/page2_findings.html", frozenset({"findings"})),
    ("app/web/templates/page2_editor.html", frozenset({"content"})),
    ("app/web/templates/home.html", frozenset({"home"})),
    ("app/web/templates/library_editor.html", frozenset()),  # no browser test loads it; test_app covers it
    ("app/web/templates/_", ALL_PAGES),
    ("app/library_editor.py", frozenset()),
    ("app/init.py", frozenset()),  # the Burp build's launcher: covered by tests.test_launcher, which the all-Python tier runs
    ("run.py", frozenset()),  # the default build's launcher: same, covered by tests.test_launcher
    ("resources/vuln_library.json", frozenset({"findings", "content"})),
    ("app/docx_", frozenset()),  # reaches the browser only through import and generate, see FILE_FEATURES
    ("resources/", frozenset()),
    ("app/", ALL_PAGES),  # models, report_service, main, workspace, storage, library: the server every page talks to
    ("tests/support.py", ALL_PAGES),
    ("tests/__init__.py", ALL_PAGES),
    ("requirements", ALL_PAGES),
    ("report_generator_burp.py", frozenset()),  # the Burp extension: same, and a Python 2.7 syntax test
    (".gitignore", frozenset()),
    ("scripts/", frozenset()),
]
FILE_FEATURES = [("app/docx_", {"import", "generate"}), ("resources/", {"import", "generate"})]


# --- what changed -----------------------------------------------------------------------------------

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text: str) -> dict[str, set[int]]:
    """New-side line numbers per file from `git diff -U0`. A pure deletion marks the lines either side."""
    changed: dict[str, set[int]] = {}
    path = None
    for line in text.splitlines():
        if line.startswith("+++ "):
            path = None if line == "+++ /dev/null" else line[6:]
            if path:
                changed.setdefault(path, set())
        elif path and (match := HUNK.match(line)):
            start, count = int(match[1]), int(match[2] if match[2] is not None else 1)
            changed[path].update(range(start, start + count) if count else (start, start + 1))
    return changed


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def changed_files() -> dict[str, set[int] | None]:
    """Every changed path, with its changed lines; None means the whole file (new, binary or deleted)."""
    lines = parse_diff(git("diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", "HEAD"))
    paths = git("diff", "--name-only", "--no-renames", "HEAD").splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    result: dict[str, set[int] | None] = {path: lines.get(path) or None for path in paths}
    result.update({path: None for path in untracked})
    return result


# --- test modules -------------------------------------------------------------------------------------

@dataclass
class Unit:
    """A method or module-level function in a test module, with the names its body mentions."""
    name: str
    cls: str | None
    start: int
    end: int
    refs: set[str] = field(default_factory=set)


@dataclass
class TestModule:
    dotted: str
    source: str
    units: list[Unit]
    imports: list[tuple[int, int]]

    def tests(self) -> list[Unit]:
        return [unit for unit in self.units if unit.cls and unit.name.startswith("test")]

    def test_id(self, unit: Unit) -> str:
        return f"{self.dotted}.{unit.cls}.{unit.name}"

    def reach(self, test: Unit) -> set[str]:
        """Names a test mentions, following the helpers it calls."""
        helpers = {unit.name: unit for unit in self.units if not unit.name.startswith("test")}
        seen, todo = set(), set(test.refs)
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            if name in helpers:
                todo |= helpers[name].refs
        return seen

    def body(self, test: Unit) -> str:
        """Source of a test plus every helper it reaches."""
        lines = self.source.splitlines()
        reach = self.reach(test)
        parts = [unit for unit in self.units if unit is test or (unit.name in reach and not unit.name.startswith("test"))]
        return "\n".join("\n".join(lines[unit.start - 1:unit.end]) for unit in parts)


def load_module(path: Path) -> TestModule | None:
    return parse_module(path.read_text(encoding="utf-8"), ".".join(path.relative_to(ROOT).with_suffix("").parts))


def parse_module(source: str, dotted: str) -> TestModule | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    units: list[Unit] = []

    def unit(node: ast.FunctionDef | ast.AsyncFunctionDef, cls: str | None) -> Unit:
        start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
        refs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        refs |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        return Unit(node.name, cls, start, node.end_lineno or start, refs)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            units += [unit(item, node.name) for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            units.append(unit(node, None))
    imports = [(node.lineno, node.end_lineno or node.lineno) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    return TestModule(dotted, source, units, imports)


def test_modules() -> dict[str, TestModule | None]:
    return {path.relative_to(ROOT).as_posix(): load_module(path) for path in sorted((ROOT / "tests").glob("test_*.py"))}


def changed_tests(module: TestModule, lines: set[int] | None) -> tuple[set[str], set[str], bool]:
    """(test ids, changed helper names, whole module?) for the changed lines of one test module."""
    if lines is None:
        return set(), set(), True
    ids: set[str] = set()
    helpers: set[str] = set()
    source_lines = module.source.splitlines()
    for number in lines:
        text = source_lines[number - 1].strip() if 0 < number <= len(source_lines) else ""
        owner = next((unit for unit in module.units if unit.start <= number <= unit.end), None)
        if owner is None:
            if not text or text.startswith("#") or any(a <= number <= b for a, b in module.imports):
                continue  # blank lines, comments and imports change no behaviour on their own
            return set(), set(), True  # a class attribute or module-level statement: rerun the module
        if owner.cls and owner.name in CLASS_WIDE:
            ids |= {module.test_id(unit) for unit in module.tests() if unit.cls == owner.cls}
        elif owner.cls and owner.name.startswith("test"):
            ids.add(module.test_id(owner))
        else:
            helpers.add(owner.name)
    for test in module.tests():
        if module.reach(test) & helpers:
            ids.add(module.test_id(test))
    return ids, helpers, False


# --- app.js regions -----------------------------------------------------------------------------------

TOP_LEVEL = re.compile(r"^  (?![\s}\])]|//)")
DECLARATION = re.compile(r"^  (?:async\s+)?(?:function\*?\s+([\w$]+)|(?:const|let|var)\s+([\w$]+))")


def app_js_pages(source: str, lines: set[int] | None) -> set[str]:
    """Pages whose code a change to app.js touches: setup() drives Setup and Findings, continuousEditor()
    drives Content, and everything else in the file (save machine, twin rules, renderers) runs on all three."""
    if lines is None:
        return set(REPORT_PAGES)
    text = source.splitlines()
    starts = [(number, DECLARATION.match(line)) for number, line in enumerate(text, 1) if TOP_LEVEL.match(line)]
    pages: set[str] = set()
    for number in lines:
        line = text[number - 1].strip() if 0 < number <= len(text) else ""
        if not line or line.startswith("//"):
            continue
        owner = next((match for start, match in reversed(starts) if start <= number), None)
        name = owner and (owner[1] or owner[2])
        pages |= {"setup": {"setup", "findings"}, "continuousEditor": {"content"}}.get(name, set(REPORT_PAGES))
    return pages


# --- browser tests by page ----------------------------------------------------------------------------

def browser_tags(module: TestModule) -> dict[str, set[str]]:
    """Test id -> pages and flows it exercises. A test nothing matches counts for every page."""
    tags = {}
    for test in module.tests():
        body = module.body(test)
        found = {page for pattern, page in PAGE_PATTERNS if pattern.search(body)} or set(ALL_PAGES)
        found |= {feature for pattern, feature in FEATURE_PATTERNS if pattern.search(body)}
        tags[module.test_id(test)] = found
    return tags


# --- tiers --------------------------------------------------------------------------------------------

@dataclass
class Selection:
    python: set[str] = field(default_factory=set)  # dotted module or test ids outside the browser module
    browser: set[str] = field(default_factory=set)  # browser test ids
    browser_module: bool = False
    reasons: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)


def select(tier: str, changed: dict[str, set[int] | None], modules: dict[str, TestModule | None]) -> Selection:
    chosen = Selection()
    if tier == "full":
        chosen.python = {module.dotted for path, module in modules.items() if module and path != BROWSER}
        chosen.browser_module = True
        chosen.reasons.append("full suite, because it was asked for")
        return chosen

    # Tier 1: the tests that were added or changed, and the tests that call a changed shared helper.
    support_helpers: set[str] = set()
    for path, lines in changed.items():
        module = modules.get(path)
        if path in modules and module is None:
            chosen.unmatched.append(f"{path} (does not parse)")
            continue
        if path == "tests/support.py" and (ROOT / path).exists():
            support = load_module(ROOT / path)
            if support:
                support_helpers |= changed_tests(support, lines)[1] if lines is not None else {unit.name for unit in support.units}
            continue
        if module is None:
            continue
        ids, _helpers, whole = changed_tests(module, lines)
        if path == BROWSER:
            if whole:
                chosen.browser_module = True
            chosen.browser |= ids
        elif whole:
            chosen.python.add(module.dotted)
        else:
            chosen.python |= ids
    if support_helpers:
        for path, module in modules.items():
            if not module:
                continue
            hits = {module.test_id(test) for test in module.tests() if module.reach(test) & support_helpers}
            (chosen.browser if path == BROWSER else chosen.python).update(hits)
    if chosen.python or chosen.browser or chosen.browser_module:
        chosen.reasons.append("the tests you added or changed")
    if tier == "iterate":
        return chosen

    # Tier 2: everything the change can reach.
    pages: set[str] = set()
    features: set[str] = set()
    python = False
    rule_copies = False
    for path, lines in changed.items():
        if path.startswith("tests/test_"):
            python = True
            continue
        if path.startswith(RULE_COPIES):
            rule_copies = True
        if path.startswith(NO_TESTS) or (path.endswith(".md") and path != "docs/DATA_MAP.md"):
            continue
        python = True  # every Python module together takes about 18 s, so any real change runs them all
        if path == "app/web/static/app.js":
            source = (ROOT / path).read_text(encoding="utf-8") if (ROOT / path).exists() else ""
            pages |= app_js_pages(source, lines)
            continue
        if path == "docs/DATA_MAP.md":
            continue  # test_app checks its twin table; no browser test reads it
        rule = next((found for prefix, found in FILE_PAGES if path.startswith(prefix)), None)
        if rule is None:
            chosen.unmatched.append(path)
            continue
        pages |= rule
        features |= next((found for prefix, found in FILE_FEATURES if path.startswith(prefix)), set())
    if python:
        chosen.python = {module.dotted for path, module in modules.items() if module and path != BROWSER}
        chosen.reasons.append("all Python test modules (about 18 s)")
    elif rule_copies:
        chosen.python.add(RULE_SYNC_TEST)
        chosen.reasons.append("the Claude rules are copies of the Copilot instructions")
    browser_module = modules.get(BROWSER)
    if (pages or features) and browser_module:
        tags = browser_tags(browser_module)
        reached = {test for test, found in tags.items() if found & pages or found & features}
        chosen.browser |= reached
        described = ", ".join(sorted(pages | features))
        chosen.reasons.append(f"browser tests for {described}")
    return chosen


# --- running ------------------------------------------------------------------------------------------

RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)


def verdict(results: list[tuple[int, str]]) -> str:
    """The unindented last line, from each run's exit code and output, so a grep for ^OK or ^FAILED finds it."""
    runs = len(results)
    failed = sum(1 for code, _ in results if code)
    if failed:
        whose = "Its output is" if failed == 1 else "Their output is"
        return f"FAILED: {failed} of {runs} run{'s' * (runs != 1)} failed. {whose} above."
    tests = sum(int(count) for _, text in results for count in RAN.findall(text))
    return f"OK: {tests} test{'s' * (tests != 1)} passed in {runs} run{'s' * (runs != 1)}"


def run(chosen: Selection, modules: dict[str, TestModule | None]) -> int:
    jobs: list[list[str]] = []
    if chosen.python:
        jobs.append(sorted(chosen.python))
    browser = sorted(chosen.browser)
    if chosen.browser_module:
        module = modules.get(BROWSER)
        browser = sorted(module.test_id(test) for test in module.tests()) if module else []
    if browser:
        chunks = 1 if len(browser) <= 8 else min(4, max(2, (os.cpu_count() or 2) // 2))
        jobs += [browser[index::chunks] for index in range(chunks)]

    def execute(targets: list[str]) -> tuple[list[str], int, str]:
        # Output goes to a file, not a pipe: Chromium helpers outlive the test process and would hold a
        # pipe open, so waiting for its end of file can take minutes after the tests have finished.
        with tempfile.TemporaryFile("w+", encoding="utf-8") as output:
            code = subprocess.run([sys.executable, "-m", "unittest", *targets], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT).returncode
            output.seek(0)
            return targets, code, output.read()

    results: list[tuple[int, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        for targets, code, text in pool.map(execute, jobs):
            results.append((code, text))
            summary = [line for line in text.splitlines() if line.startswith(("Ran ", "OK", "FAILED"))]
            label = f"{len(targets)} target(s)" if len(targets) > 3 else " ".join(targets)
            print(f"  {label}: {' '.join(summary) or 'no summary'}")
            if code:
                print(text[-6000:])
    print(verdict(results))
    return 1 if any(code for code, _ in results) else 0


def main(argv: list[str]) -> int:
    tier = "full" if "--full" in argv else "affected" if "--affected" in argv else "iterate"
    changed = changed_files()
    if tier != "full" and not changed:
        print("Tests: none — working tree matches HEAD.")
        return 0
    modules = test_modules()
    chosen = select(tier, changed, modules)
    if tier != "full":
        print(f"Changed ({len(changed)}):")
        for path in sorted(changed):
            print(f"  {path}")
    if chosen.unmatched:
        print("\nNo rule for these — decide by hand:")
        for path in chosen.unmatched:
            print(f"  {path}")
    browser_count = "all" if chosen.browser_module else str(len(chosen.browser))
    if not (chosen.python or chosen.browser or chosen.browser_module):
        hint = " Run --affected before calling it done." if tier == "iterate" else ""
        print(f"\nTests: none — no test was added or changed.{hint}" if tier == "iterate" else "\nTests: none — nothing changed that a test asserts on.")
        return 0
    print(f"\nTests: {tier} — {len(chosen.python)} Python target(s), {browser_count} browser test(s): {'; '.join(chosen.reasons)}")
    if "--run" in argv:
        return run(chosen, modules)
    for target in sorted(chosen.python):
        print(f"  {target}")
    if chosen.browser_module:
        print("  tests.test_browser (whole module)")
    else:
        for target in sorted(chosen.browser):
            print(f"  {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
