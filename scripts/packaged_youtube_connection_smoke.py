"""Run offline guided-auth and GUI startup smokes against the packaged EXE."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def _run(executable: Path, argument: str, result: Path, timeout: int = 30) -> dict:
    completed = subprocess.run(
        [str(executable), argument, str(result)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        shell=False,
        check=False,
        close_fds=True,
        timeout=timeout,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(
            f"Packaged smoke {argument} exited {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    payload = json.loads(result.read_text(encoding="utf-8"))
    if not payload.get("passed"):
        raise RuntimeError(f"Packaged smoke {argument} failed: {payload}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "executable",
        nargs="?",
        type=Path,
        default=Path("dist/NeuralExtractorV3.exe"),
    )
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        raise SystemExit(f"Packaged executable not found: {executable}")

    with tempfile.TemporaryDirectory(prefix="neural-extractor-packaged-smoke-") as temporary:
        root = Path(temporary)
        connection = _run(
            executable,
            "--internal-youtube-connection-smoke",
            root / "connection.json",
        )
        gui = _run(
            executable,
            "--internal-gui-startup-smoke",
            root / "gui.json",
        )
    print(json.dumps({"connection": connection, "gui": gui}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
