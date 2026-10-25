"""Engine abstraction: everything DBMS-specific lives in subclasses of Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from dbon.instance import Instance


class EngineError(Exception):
    pass


@dataclass
class ExecSpec:
    """A command to run inside the container via `docker exec`."""

    cmd: list[str]
    user: str | None = None
    env: dict[str, str] = field(default_factory=dict)


class Engine:
    name: ClassVar[str]
    label: ClassVar[str]
    aliases: ClassVar[tuple[str, ...]] = ()
    port: ClassVar[int]  # container port, also the preferred host port
    admin_user: ClassVar[str]
    default_version: ClassVar[str]
    # version -> spec dict (at least "image"; engines add their own keys)
    versions: ClassVar[dict[str, dict[str, Any]]]
    base_image: ClassVar[str | None] = None  # used for versions not in the table
    probe_sql: ClassVar[str] = "SELECT 1;"
    dialect: ClassVar[str]

    # ---- versions -----------------------------------------------------------
    def spec(self, version: str) -> dict[str, Any]:
        if version in self.versions:
            return dict(self.versions[version])
        if self.base_image is None:
            known = ", ".join(self.versions)
            raise EngineError(f"{self.name} supports only the following versions: {known}")
        return self.custom_spec(version)

    def custom_spec(self, version: str) -> dict[str, Any]:
        return {"image": f"{self.base_image}:{version}"}

    def prepare(self, inst: Instance) -> None:
        """Hook run before compose file generation (may pull/inspect the image)."""
        spec = self.spec(inst.version)
        inst.extra.setdefault("volume_path", spec.get("volume_path"))

    # ---- compose ------------------------------------------------------------
    def environment(self, inst: Instance) -> dict[str, str]:
        raise NotImplementedError

    def healthcheck(self, inst: Instance) -> dict[str, Any] | None:
        return None

    def command(self, inst: Instance) -> list[str] | None:
        return None

    def service_extras(self, inst: Instance) -> dict[str, Any]:
        return {}

    def compose(self, inst: Instance) -> dict[str, Any]:
        labels = {
            "dbon.managed": "true",
            "dbon.instance": inst.name,
            "dbon.engine": self.name,
            "dbon.version": inst.version,
        }
        env = {"TZ": inst.timezone, **self.environment(inst)}
        service: dict[str, Any] = {
            "image": inst.image,
            "container_name": inst.container,
            "restart": inst.restart,
            "environment": env,
            "ports": [f"{inst.port}:{self.port}"],
            "volumes": [f"data:{inst.extra['volume_path']}"],
            "labels": labels,
        }
        cmd = self.command(inst)
        if cmd:
            service["command"] = cmd
        if inst.mem_limit:
            service["mem_limit"] = inst.mem_limit
        hc = self.healthcheck(inst)
        if hc:
            service["healthcheck"] = hc
        service.update(self.service_extras(inst))
        return {
            "name": inst.project,
            "services": {"db": service},
            "volumes": {"data": {"labels": {"dbon.managed": "true", "dbon.instance": inst.name}}},
        }

    # ---- SQL execution ------------------------------------------------------
    def exec_sql(self, inst: Instance, path: str, *, admin: bool, admin_password: str | None = None) -> ExecSpec:
        """Command that runs the SQL file at `path` (inside the container)."""
        raise NotImplementedError

    def shell(self, inst: Instance, *, admin: bool) -> ExecSpec:
        raise NotImplementedError

    def wrap_script(self, sql: str) -> str:
        return sql

    def probe_passwords(self, inst: Instance) -> list[str]:
        return [inst.admin_password]

    def bootstrap_sql(self, inst: Instance, admin_password_in_use: str) -> str:
        raise NotImplementedError

    # ---- info ---------------------------------------------------------------
    def database_label(self, inst: Instance) -> str:
        return inst.database

    def jdbc_url(self, inst: Instance) -> str:
        raise NotImplementedError

    def info(self, inst: Instance) -> dict[str, Any]:
        return {
            "engine": f"{self.label} {inst.version}",
            "image": inst.image,
            "container": inst.container,
            "host": "localhost",
            "port": inst.port,
            "database": self.database_label(inst),
            "user": inst.user,
            "password": inst.password,
            "admin_user": self.admin_user,
            "admin_password": inst.admin_password,
            "jdbc": self.jdbc_url(inst),
        }
