"""Thin subprocess wrappers around the docker CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


class DockerError(Exception):
    pass


def _docker() -> str:
    exe = shutil.which("docker")
    if not exe:
        raise DockerError("Docker executable not found. Check that Docker Desktop/Engine is installed.")
    return exe


def run(
    args: Sequence[str],
    *,
    capture: bool = True,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    cmd = [_docker(), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=input_text,
        )
    except OSError as e:
        raise DockerError(f"docker run failed: {e}") from e
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() if capture else ""
        raise DockerError(f"docker {' '.join(args[:3])} failed (exit {proc.returncode})\n{detail}".rstrip())
    return proc


def run_interactive(args: Sequence[str]) -> int:
    return subprocess.call([_docker(), *args])


def compose(compose_file: Path, project: str, *args: str, capture: bool = False, check: bool = True):
    return run(
        ["compose", "-f", str(compose_file), "-p", project, *args],
        capture=capture,
        check=check,
    )


def inspect_container(name: str) -> dict | None:
    proc = run(["container", "inspect", name], check=False)
    if proc.returncode != 0:
        return None
    data = json.loads(proc.stdout)
    return data[0] if data else None


def container_status(name: str) -> str:
    """Return e.g. 'running (healthy)', 'exited', 'missing'."""
    info = inspect_container(name)
    if not info:
        return "missing"
    state = info.get("State", {})
    status = state.get("Status", "unknown")
    health = (state.get("Health") or {}).get("Status")
    return f"{status} ({health})" if health and status == "running" else status


def container_health(name: str) -> str | None:
    info = inspect_container(name)
    if not info:
        return None
    return ((info.get("State") or {}).get("Health") or {}).get("Status")


def image_env(image: str) -> dict[str, str]:
    proc = run(["image", "inspect", image, "--format", "{{json .Config.Env}}"], check=False)
    if proc.returncode != 0:
        return {}
    env = json.loads(proc.stdout.strip() or "[]") or []
    return dict(item.split("=", 1) for item in env if "=" in item)


def pull(image: str) -> None:
    run(["pull", image], capture=False)


def image_exists(image: str) -> bool:
    return run(["image", "inspect", image], check=False).returncode == 0


def copy_to(container: str, src: Path, dest: str) -> None:
    run(["cp", str(src), f"{container}:{dest}"])


def exec_(
    container: str,
    cmd: Sequence[str],
    *,
    user: str | None = None,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess:
    args = ["exec"]
    if user:
        args += ["-u", user]
    for k, v in (env or {}).items():
        args += ["-e", f"{k}={v}"]
    args += [container, *cmd]
    return run(args, check=check)


def exec_interactive(container: str, cmd: Sequence[str], *, user: str | None = None, env: dict[str, str] | None = None) -> int:
    args = ["exec", "-it"]
    if user:
        args += ["-u", user]
    for k, v in (env or {}).items():
        args += ["-e", f"{k}={v}"]
    return run_interactive([*args, container, *cmd])


def published_host_ports() -> set[int]:
    """Host ports published by any running container (dbon or not)."""
    proc = run(["ps", "--format", "{{.Ports}}"], check=False)
    ports: set[int] = set()
    if proc.returncode != 0:
        return ports
    for line in proc.stdout.splitlines():
        for part in line.split(","):
            part = part.strip()
            if "->" not in part:
                continue
            host = part.split("->", 1)[0]
            port = host.rsplit(":", 1)[-1]
            if "-" in port:
                lo, hi = port.split("-", 1)
                if lo.isdigit() and hi.isdigit():
                    ports.update(range(int(lo), int(hi) + 1))
            elif port.isdigit():
                ports.add(int(port))
    return ports


def list_by_label(kind: str, label: str) -> list[str]:
    """kind: 'container' or 'volume'."""
    if kind == "container":
        proc = run(["ps", "-a", "--filter", f"label={label}", "--format", "{{.Names}}"], check=False)
    else:
        proc = run(["volume", "ls", "--filter", f"label={label}", "--format", "{{.Name}}"], check=False)
    return [x for x in proc.stdout.split() if x] if proc.returncode == 0 else []
