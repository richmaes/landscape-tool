"""Shared test setup, applied to every test file automatically."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # before any Qt import

import pytest


@pytest.fixture(autouse=True)
def _answer_close_prompts_with_discard():
    """In conftest.py so it covers *every* test file: a real hang
    (2026-09-25) came from a test file that forgot to import it — placing a
    model left its window unsaved, and the close prompt at teardown waited
    forever. Also accepts File > Export's options dialog — see below.

    Closing an EditorWindow with unsaved changes now asks Save/Discard/
    Cancel via a modal QMessageBox.question — and pytest-qt closes every
    registered window at teardown, so any test that leaves edits unsaved
    would block forever on a dialog nobody answers (a real hang, found
    the first time this ran). Autouse, so it's set up before `qtbot` and
    torn down after it: still in effect during qtbot's window cleanup.
    Tests that check the prompt itself override it with `monkeypatch`."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QMessageBox

    from PySide6.QtWidgets import QDialog

    from landscape.editor import ExportOptionsDialog

    # Same hazard, same fix: File > Export shows a modal options dialog
    # after the file picker. Accept it with its defaults unless a test says
    # otherwise.
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Discard), patch.object(
        ExportOptionsDialog, "exec", return_value=QDialog.Accepted
    ):
        yield
