"""Point the app at a throwaway data folder before any test imports app.main.

app/main.py resolves its data folder when it is imported, so this must run first. It does when tests
run as `python -m unittest tests.<module>` or through scripts/relevant_tests.py; `discover -s tests`
imports the modules without their package and would write to the real data/ folder.
"""
import os
import tempfile

# Assigned outright, so a value exported in the shell can never aim a test run at real drafts.
# ignore_cleanup_errors: on Windows the error log is still open when the interpreter exits.
_DATA = tempfile.TemporaryDirectory(prefix="vulnreport-tests-", ignore_cleanup_errors=True)
os.environ["VULNREPORT_DATA_DIR"] = _DATA.name
