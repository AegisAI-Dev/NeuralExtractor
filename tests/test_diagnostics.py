import subprocess

from neural_extractor_v3.core import diagnostics
from neural_extractor_v3.core.auth import AuthResolution, AuthStrategy, CookieFileStatus
from neural_extractor_v3.core.downloader import YtdlpRunResult
from neural_extractor_v3.core.js_runtime import JavaScriptRuntimeStatus
from neural_extractor_v3.models import DownloadOptions


def test_diagnostics_never_logs_cookie_contents(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tFALSE\t0\tSID\tsuper-secret-token\n",
        encoding="utf-8",
    )

    report = diagnostics.run_support_diagnostics(
        DownloadOptions(output_dir=tmp_path / "out", cookie_file=cookie_file),
        run_probe=False,
        check_github=False,
    )
    text = report.text()

    assert "super-secret-token" not in text
    assert "contents=not logged" in text
    assert "size=" in text
    assert str(cookie_file) in text


def test_format_probe_is_safe_and_uses_js_runtime(tmp_path, monkeypatch):
    node_path = tmp_path / "node.exe"
    captured_opts = {}
    auth_resolution = AuthResolution(
        strategies=[
            AuthStrategy(
                kind="none",
                display_name="no authentication",
                ydl_options={},
                attempted_auth=False,
            )
        ],
        messages=[],
        cookie_file_status=CookieFileStatus(None, False, "cookies.txt not loaded"),
        browser_source=None,
        browser_sources=[],
    )

    class FakeDownloadEngine:
        def __init__(self, options):
            self.js_runtime_status = JavaScriptRuntimeStatus(
                True, "node", node_path, "v22.17.0"
            )

        def _run_yt_dlp(self, url, options, *, discover_only=False):
            assert discover_only
            captured_opts.update(options)
            return YtdlpRunResult(formats=[{"format_id": "18"}])

    def fake_run_command(args: list[str], *, timeout: int):
        if args and args[0] == "tasklist":
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="v22.17.0\n", stderr="")
        if "-e" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="neural-extractor-node-ok",
                stderr="",
            )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(
        diagnostics,
        "ensure_youtube_js_runtime",
        lambda: JavaScriptRuntimeStatus(True, "node", node_path, "v22.17.0"),
    )
    monkeypatch.setattr(
        diagnostics,
        "resolve_auth_strategies",
        lambda _cookie_file, **_kwargs: auth_resolution,
    )
    monkeypatch.setattr(diagnostics, "DownloadEngine", FakeDownloadEngine)
    monkeypatch.setattr(diagnostics, "_run_command", fake_run_command)

    report = diagnostics.run_support_diagnostics(
        DownloadOptions(output_dir=tmp_path / "out"),
        probe_url="https://www.youtube.com/watch?v=abc123",
        check_github=False,
    )

    assert captured_opts["listformats"] is True
    assert captured_opts["skip_download"] is True
    assert captured_opts["simulate"] == "list_only"
    assert captured_opts["noplaylist"] is True
    assert captured_opts["js_runtimes"] == {"node": {"path": str(node_path)}}
    assert captured_opts["remote_components"] == ["ejs:github"]
    assert "[PASS] EJS GitHub remote component: --remote-components ejs:github enabled" in report.text()
    assert "[PASS] Safe yt-dlp format probe: 1 formats" in report.text()
