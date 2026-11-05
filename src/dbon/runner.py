"""Running SQL inside instance containers: readiness wait, bootstrap, dummy data."""

from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable

from dbon import docker, engines
from dbon.dummy import render
from dbon.instance import Instance

Log = Callable[[str], None]


class RunError(Exception):
    pass


def _noop(_: str) -> None:
    pass


def run_sql(
    inst: Instance,
    sql: str,
    *,
    admin: bool,
    admin_password: str | None = None,
    check: bool = True,
):
    engine = engines.get(inst.engine)
    script = engine.wrap_script(sql)
    remote = f"/tmp/dbon-{uuid.uuid4().hex}.sql"
    with tempfile.TemporaryDirectory(prefix="dbon-") as tmp:
        local = Path(tmp) / "script.sql"
        local.write_bytes(script.encode("utf-8"))
        docker.copy_to(inst.container, local, remote)
    try:
        spec = engine.exec_sql(inst, remote, admin=admin, admin_password=admin_password)
        proc = docker.exec_(inst.container, spec.cmd, user=spec.user, env=spec.env)
    finally:
        docker.exec_(inst.container, ["rm", "-f", remote], user="0")
    failed = proc.returncode != 0 or _has_error(inst.engine, proc.stdout + proc.stderr)
    if check and failed:
        out = (proc.stdout + proc.stderr).strip()
        raise RunError(f"SQL execution failed (exit code {proc.returncode})\n{_tail(out, 40)}")
    return proc


def _has_error(engine: str, output: str) -> bool:
    # csql reports statement errors but still exits 0
    return engine == "cubrid" and "ERROR:" in output


def _tail(text: str, n: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def wait_ready(inst: Instance, timeout: int, log: Log = _noop) -> str:
    """Block until the admin account can run a query. Returns the admin password that worked."""
    engine = engines.get(inst.engine)
    deadline = time.monotonic() + timeout
    last_note = ""
    started = time.monotonic()
    while True:
        info = docker.inspect_container(inst.container)
        if info is None:
            raise RunError(f"Container {inst.container} does not exist")
        state = info.get("State", {})
        status = state.get("Status")
        health = (state.get("Health") or {}).get("Status")
        if status in ("exited", "dead"):
            logs = docker.run(["logs", "--tail", "30", inst.container], check=False)
            raise RunError(
                f"Container has stopped (exit code {state.get('ExitCode')})\n"
                f"{_tail(logs.stdout + logs.stderr, 30)}"
            )

        note = f"status={status}" + (f", health={health}" if health else "")
        if status == "running" and health in (None, "healthy"):
            if not engine.setup_finished(inst, state.get("StartedAt", "")):
                note += ", waiting for image setup"
            else:
                for pw in engine.probe_passwords(inst):
                    proc = run_sql(inst, engine.probe_sql, admin=True, admin_password=pw, check=False)
                    if proc.returncode == 0 and not _has_error(inst.engine, proc.stdout + proc.stderr):
                        for spec in engine.on_ready(inst):
                            docker.exec_(inst.container, spec.cmd, user=spec.user, env=spec.env, check=True)
                        return pw
                note += ", waiting for connection"
        if note != last_note:
            log(f"  [{int(time.monotonic() - started)}s] {note}")
            last_note = note
        if time.monotonic() > deadline:
            raise RunError(
                f"Container did not become ready within {timeout} seconds. "
                f"Check with `dbon logs {inst.name}`."
            )
        time.sleep(3)


def bootstrap(inst: Instance, admin_password_in_use: str) -> None:
    engine = engines.get(inst.engine)
    run_sql(inst, engine.bootstrap_sql(inst, admin_password_in_use), admin=True, admin_password=admin_password_in_use)
    inst.bootstrapped = True
    inst.save()


def seed(inst: Instance, rows: int, seed_value: int | None = None) -> Path:
    engine = engines.get(inst.engine)
    sql = render(engine.dialect, rows, seed_value)
    path = inst.dir / "seed.sql"
    path.write_text(sql, encoding="utf-8")
    run_sql(inst, sql, admin=False)
    return path
