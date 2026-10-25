"""Instance model, persistence under ~/.dbon/instances and name/port allocation."""

from __future__ import annotations

import json
import re
import shutil
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from dbon.config import dbon_home

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

@dataclass
class Instance:
    name: str
    engine: str
    version: str
    image: str
    port: int
    user: str
    password: str
    admin_password: str
    database: str
    timezone: str = "Asia/Seoul"
    restart: str = "no"
    mem_limit: str | None = None
    timeout: int = 300
    rows: int = 100
    bootstrapped: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def project(self) -> str:
        return f"dbon-{self.name}"

    @property
    def container(self) -> str:
        return f"dbon-{self.name}"

    @property
    def volume(self) -> str:
        return f"dbon-{self.name}_data"

    @property
    def dir(self) -> Path:
        return instances_dir() / self.name

    @property
    def compose_file(self) -> Path:
        return self.dir / "docker-compose.yml"

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "instance.json").write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )


def instances_dir() -> Path:
    return dbon_home() / "instances"


def load(name: str) -> Instance | None:
    path = instances_dir() / name / "instance.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Instance(**data)


def load_all() -> list[Instance]:
    root = instances_dir()
    if not root.exists():
        return []
    result = []
    for d in sorted(root.iterdir()):
        if (d / "instance.json").exists():
            inst = load(d.name)
            if inst:
                result.append(inst)
    return result


def delete_dir(inst: Instance) -> None:
    shutil.rmtree(inst.dir, ignore_errors=True)

def default_name(engine: str, version: str, taken: Iterable[str]) -> str:
    base = f"{engine}{re.sub(r'[^a-z0-9]', '', version.lower())}"
    taken = set(taken)
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def validate_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise ValueError(
            f"Instance name '{name}' may contain only lowercase letters, digits, hyphens (-), and underscores (_)"
        )


def host_port_free(port: int) -> bool:
    for family, addr in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET, "127.0.0.1")):
        with socket.socket(family, socket.SOCK_STREAM) as s:
            try:
                s.bind((addr, port))
            except OSError:
                return False
    return True


def allocate_port(start: int, reserved: Iterable[int], is_free=host_port_free, limit: int = 200) -> int:
    reserved = set(reserved)
    for port in range(start, start + limit):
        if port in reserved:
            continue
        if is_free(port):
            return port
    raise RuntimeError(
        f"No available port found in the range {start}-{start + limit - 1}"
    )
