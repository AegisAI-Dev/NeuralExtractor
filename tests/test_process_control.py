from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from neural_extractor_v3.core.process_control import (
    OwnedProcessSupervisor,
    ProcessCancelledError,
    ProcessInactivityTimeoutError,
    ProcessLaunchError,
    ProcessLimits,
    ProcessOutcome,
    ProcessPhase,
    ProcessTotalTimeoutError,
    RecoveryState,
    is_process_running,
    recover_owned_process,
)


def limits(
    *,
    inactivity: float = 1.0,
    total: float = 4.0,
    status: float = 0.1,
) -> ProcessLimits:
    return ProcessLimits(
        inactivity_timeout=inactivity,
        total_timeout=total,
        status_interval=status,
        termination_grace=0.35,
        force_kill_wait=0.75,
        poll_interval=0.02,
        pipe_join_timeout=0.75,
    )


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def force_stop_test_process(pid: int) -> None:
    """Last-resort cleanup for PIDs created by this test module only."""
    if pid <= 0 or pid == os.getpid() or not is_process_running(pid):
        return
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
        subprocess.run(
            [str(taskkill), "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
        if is_process_running(pid):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)


def child_tree_script(child_pid_file: Path | None = None) -> str:
    write_pid = ""
    if child_pid_file is not None:
        write_pid = f"Path({str(child_pid_file)!r}).write_text(str(child.pid))"
    return textwrap.dedent(
        f"""
        import subprocess
        import sys
        import time
        from pathlib import Path

        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            shell=False,
        )
        {write_pid}
        print(f"CHILD_PID={{child.pid}}", flush=True)
        time.sleep(60)
        """
    )


def test_ownership_record_failure_terminates_the_just_launched_process(
    tmp_path, monkeypatch
):
    launched_pids = []
    supervisor = OwnedProcessSupervisor(
        limits(),
        ownership_record=tmp_path / "owned-process.json",
    )

    def fail_record(pid, identity):
        launched_pids.append(pid)
        raise OSError("controlled record failure")

    monkeypatch.setattr(supervisor, "_write_ownership_record", fail_record)

    with pytest.raises(ProcessLaunchError, match="owned tree was terminated"):
        supervisor.run([sys.executable, "-c", "import time; time.sleep(60)"])

    assert launched_pids
    assert not is_process_running(launched_pids[0])


def test_stdin_output_and_heartbeats_keep_an_active_attempt_alive(tmp_path):
    statuses = []
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    record = tmp_path / "owned-process.json"
    script = textwrap.dedent(
        """
        import json
        import sys
        import time

        payload = json.loads(sys.stdin.read())
        for index in range(5):
            print(f"{payload['message']} {index}", flush=True)
            if index == 2:
                print("stderr activity", file=sys.stderr, flush=True)
            time.sleep(0.08)
        """
    )
    supervisor = OwnedProcessSupervisor(
        limits(inactivity=0.18, total=3.0, status=0.09),
        ownership_record=record,
    )

    result = supervisor.run(
        [sys.executable, "-c", script],
        stdin_data=json.dumps({"message": "progress"}),
        stdout_callback=stdout_chunks.append,
        stderr_callback=stderr_chunks.append,
        status_callback=statuses.append,
    )

    assert result.outcome is ProcessOutcome.EXITED
    assert result.returncode == 0
    assert "progress 0" in result.stdout
    assert "progress 4" in "".join(stdout_chunks)
    assert "stderr activity" in "".join(stderr_chunks)
    assert statuses[0].phase is ProcessPhase.STARTED
    assert any(status.phase is ProcessPhase.ACTIVE for status in statuses)
    assert statuses[-1].phase is ProcessPhase.EXITED
    assert len(statuses) <= 8
    assert supervisor.current_pid is None
    assert not supervisor.running
    assert not record.exists()


def test_no_output_triggers_inactivity_timeout_and_cleans_process(tmp_path):
    record = tmp_path / "inactivity.json"
    supervisor = OwnedProcessSupervisor(
        limits(inactivity=0.2, total=3.0),
        ownership_record=record,
    )

    with pytest.raises(ProcessInactivityTimeoutError) as raised:
        supervisor.run([sys.executable, "-c", "import time; time.sleep(60)"])

    result = raised.value.result
    assert result.outcome is ProcessOutcome.INACTIVITY_TIMEOUT
    assert result.pid is not None
    assert not wait_until(lambda: is_process_running(result.pid), timeout=0.1)
    assert supervisor.current_pid is None
    assert not record.exists()


def test_continuous_output_still_triggers_total_attempt_timeout():
    script = textwrap.dedent(
        """
        import time
        while True:
            print("still active", flush=True)
            time.sleep(0.04)
        """
    )
    supervisor = OwnedProcessSupervisor(limits(inactivity=0.16, total=0.35))

    with pytest.raises(ProcessTotalTimeoutError) as raised:
        supervisor.run([sys.executable, "-c", script])

    result = raised.value.result
    assert result.outcome is ProcessOutcome.TOTAL_TIMEOUT
    assert result.pid is not None
    assert result.stdout.count("still active") >= 3
    assert not wait_until(lambda: is_process_running(result.pid), timeout=0.1)


def test_timeout_terminates_owned_child_process():
    supervisor = OwnedProcessSupervisor(limits(inactivity=0.25, total=3.0))

    with pytest.raises(ProcessInactivityTimeoutError) as raised:
        supervisor.run([sys.executable, "-c", child_tree_script()])

    match = re.search(r"CHILD_PID=(\d+)", raised.value.result.stdout)
    assert match is not None
    child_pid = int(match.group(1))
    try:
        assert wait_until(lambda: not is_process_running(child_pid), timeout=3.0)
    finally:
        force_stop_test_process(child_pid)


def test_user_cancellation_terminates_tree_and_supervisor_can_be_reused():
    supervisor = OwnedProcessSupervisor(limits(inactivity=5.0, total=10.0))
    output: list[str] = []
    child_ready = threading.Event()
    finished = threading.Event()
    captured: dict[str, object] = {}

    def on_stdout(text: str) -> None:
        output.append(text)
        if re.search(r"CHILD_PID=\d+", "".join(output)):
            child_ready.set()

    def run_stuck_tree() -> None:
        try:
            captured["result"] = supervisor.run(
                [sys.executable, "-c", child_tree_script()],
                stdout_callback=on_stdout,
            )
        except BaseException as exc:  # captured for assertion on the test thread
            captured["error"] = exc
        finally:
            finished.set()

    thread = threading.Thread(target=run_stuck_tree, daemon=True)
    thread.start()
    try:
        assert child_ready.wait(timeout=5.0)
        active_pid = supervisor.current_pid
        assert active_pid is not None

        supervisor.cancel()
        assert finished.wait(timeout=6.0)
        thread.join(timeout=1.0)

        error = captured.get("error")
        assert isinstance(error, ProcessCancelledError)
        assert error.result.outcome is ProcessOutcome.CANCELLED
        match = re.search(r"CHILD_PID=(\d+)", error.result.stdout)
        assert match is not None
        child_pid = int(match.group(1))
        assert wait_until(lambda: not is_process_running(child_pid), timeout=3.0)
        assert not is_process_running(active_pid)

        supervisor.reset()
        second = supervisor.run([sys.executable, "-c", "print('second job', flush=True)"])
        assert second.returncode == 0
        assert second.outcome is ProcessOutcome.EXITED
        assert "second job" in second.stdout
    finally:
        supervisor.cancel()
        thread.join(timeout=6.0)
        match = re.search(r"CHILD_PID=(\d+)", "".join(output))
        if match is not None:
            force_stop_test_process(int(match.group(1)))


def test_cancelled_token_prevents_a_new_attempt_from_spawning():
    supervisor = OwnedProcessSupervisor(limits())
    supervisor.cancel()

    with pytest.raises(ProcessCancelledError) as raised:
        supervisor.run([sys.executable, "-c", "raise SystemExit(99)"])

    assert raised.value.result.pid is None
    assert raised.value.result.outcome is ProcessOutcome.CANCELLED


def test_crashed_owner_record_recovers_only_its_exact_process_tree(tmp_path):
    record = tmp_path / "owned-process.json"
    nested_pid_file = tmp_path / "nested-pid.txt"
    helper_code = textwrap.dedent(
        """
        import sys
        from neural_extractor_v3.core.process_control import (
            OwnedProcessSupervisor,
            ProcessLimits,
        )

        supervisor = OwnedProcessSupervisor(
            ProcessLimits(
                inactivity_timeout=30,
                total_timeout=60,
                status_interval=10,
                termination_grace=0.5,
                force_kill_wait=0.5,
                poll_interval=0.05,
                pipe_join_timeout=0.5,
            ),
            ownership_record=sys.argv[1],
        )
        supervisor.run([sys.executable, "-c", sys.argv[3], sys.argv[2]])
        """
    )
    source_root = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(source_root), env.get("PYTHONPATH", "")) if part
    )
    helper = subprocess.Popen(
        [
            sys.executable,
            "-c",
            helper_code,
            str(record),
            str(nested_pid_file),
            child_tree_script(nested_pid_file),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        env=env,
    )
    owned_pid = 0
    nested_pid = 0
    try:
        assert wait_until(lambda: record.exists() and nested_pid_file.exists(), timeout=6.0)
        owned_pid = int(json.loads(record.read_text(encoding="utf-8"))["pid"])
        nested_pid = int(nested_pid_file.read_text(encoding="utf-8"))
        assert is_process_running(owned_pid)
        assert is_process_running(nested_pid)

        helper.kill()
        helper.wait(timeout=3.0)
        assert wait_until(lambda: not is_process_running(helper.pid), timeout=2.0)

        recovery = recover_owned_process(
            record,
            termination_grace=0.4,
            force_kill_wait=0.8,
        )

        assert recovery.state is RecoveryState.TERMINATED
        assert recovery.pid == owned_pid
        assert wait_until(lambda: not is_process_running(owned_pid), timeout=3.0)
        assert wait_until(lambda: not is_process_running(nested_pid), timeout=3.0)
        assert not record.exists()
    finally:
        if helper.poll() is None:
            helper.kill()
            helper.wait(timeout=3.0)
        if record.exists():
            recover_owned_process(record, termination_grace=0.2, force_kill_wait=0.5)
        force_stop_test_process(owned_pid)
        force_stop_test_process(nested_pid)


def test_shell_command_strings_are_rejected():
    supervisor = OwnedProcessSupervisor(limits())

    with pytest.raises(TypeError, match="argv sequence"):
        supervisor.run(f"{sys.executable} -c print('unsafe')")
