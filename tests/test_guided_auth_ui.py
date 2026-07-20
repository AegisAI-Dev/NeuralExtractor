from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from neural_extractor_v3.core import youtube_connection as connection_module
from neural_extractor_v3.gui import main_window as gui_module
from neural_extractor_v3.models import DownloadJob


@pytest.fixture
def main_window(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(gui_module, "QSettings", lambda *_args: settings)
    monkeypatch.setattr(connection_module, "app_data_dir", lambda: tmp_path / "app-data")
    monkeypatch.setattr(
        gui_module,
        "ensure_youtube_js_runtime",
        lambda: SimpleNamespace(found=True, diagnostic="JavaScript runtime found for test"),
    )
    window = gui_module.MainWindow()
    yield application, window
    window.close()
    settings.clear()


def test_authentication_required_jobs_open_one_assistant_and_resume_originals(main_window):
    application, window = main_window
    first = DownloadJob("https://www.youtube.com/watch?v=first")
    second = DownloadJob("https://www.youtube.com/watch?v=second")
    window._append_job(first)
    window._append_job(second)
    prompts = []
    resumes = []
    window.connect_youtube = lambda **kwargs: prompts.append(kwargs) or True
    window._resume_authenticated_jobs = lambda: resumes.append(True)

    window.on_job_finished(first.job_id, False, "Authentication required", "authentication_required")
    window.on_job_finished(second.job_id, False, "Authentication required", "authentication_required")
    application.processEvents()
    application.processEvents()

    assert len(prompts) == 1
    assert window.table.item(window.row_by_job_id[first.job_id], 2).text() == "Queued"
    assert window.table.item(window.row_by_job_id[second.job_id], 2).text() == "Queued"
    assert window._auth_retry_counts[first.job_id] == 1
    assert window._auth_retry_counts[second.job_id] == 1
    assert resumes

    window.on_job_finished(first.job_id, False, "Authentication required", "authentication_required")
    application.processEvents()
    assert len(prompts) == 1


def test_cancelled_connection_does_not_resume_original_job(main_window):
    application, window = main_window
    job = DownloadJob("https://www.youtube.com/watch?v=cancelled")
    window._append_job(job)
    resumes = []
    window.connect_youtube = lambda **_kwargs: False
    window._resume_authenticated_jobs = lambda: resumes.append(True)

    window.on_job_finished(job.job_id, False, "Authentication required", "authentication_required")
    application.processEvents()
    application.processEvents()

    row = window.row_by_job_id[job.job_id]
    assert window.table.item(row, 2).text() == "Failed"
    assert "cancelled" in window.table.item(row, 4).text().casefold()
    assert not resumes
