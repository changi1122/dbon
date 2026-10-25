from __future__ import annotations

from dbon.engines.base import Engine, ExecSpec


def _major(version: str) -> int:
    head = version.split(".")[0].split("-")[0]
    return int(head) if head.isdigit() else 999


class Postgres(Engine):
    name = "postgres"
    label = "PostgreSQL"
    aliases = ("pg", "postgresql", "postgre")
    port = 5432
    admin_user = "postgres"
    default_version = "18"
    base_image = "postgres"
    dialect = "postgres"
    versions = {v: {"image": f"postgres:{v}"} for v in ("13", "14", "15", "16", "17", "18")}

    def spec(self, version):
        spec = super().spec(version)
        # 18+ images moved PGDATA under a versioned subdirectory of /var/lib/postgresql
        spec["volume_path"] = "/var/lib/postgresql" if _major(version) >= 18 else "/var/lib/postgresql/data"
        return spec

    def environment(self, inst):
        return {"POSTGRES_USER": self.admin_user, "POSTGRES_PASSWORD": inst.admin_password}

    def healthcheck(self, inst):
        return {
            "test": ["CMD-SHELL", f"pg_isready -h 127.0.0.1 -U {self.admin_user}"],
            "interval": "5s", "timeout": "5s", "retries": 20, "start_period": "10s",
        }

    def _psql(self, inst, admin, admin_password=None):
        if admin:
            user, pw, db = self.admin_user, admin_password or inst.admin_password, "postgres"
        else:
            user, pw, db = inst.user, inst.password, inst.database
        return ["psql", "-h", "127.0.0.1", "-U", user, "-d", db], {"PGPASSWORD": pw}

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        cmd, env = self._psql(inst, admin, admin_password)
        return ExecSpec([*cmd, "-v", "ON_ERROR_STOP=1", "-q", "-f", path], env=env)

    def shell(self, inst, *, admin):
        cmd, env = self._psql(inst, admin)
        return ExecSpec(cmd, env=env)

    def bootstrap_sql(self, inst, admin_password_in_use):
        u, pw, db = inst.user, inst.password, inst.database
        return f"""\
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{u}') THEN
    CREATE ROLE "{u}" LOGIN PASSWORD '{pw}';
  ELSE
    ALTER ROLE "{u}" LOGIN PASSWORD '{pw}';
  END IF;
END
$$;
SELECT 'CREATE DATABASE "{db}" OWNER "{u}"' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{db}')\\gexec
"""

    def jdbc_url(self, inst):
        return f"jdbc:postgresql://localhost:{inst.port}/{inst.database}"
