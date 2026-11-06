from __future__ import annotations

from dbon.engines.base import Engine, EngineError, ExecSpec

DATA_DIR = "/var/lib/firebird/data"


class Firebird(Engine):
    name = "firebird"
    label = "Firebird"
    aliases = ("fb",)
    port = 3050
    admin_user = "SYSDBA"
    default_version = "5"
    base_image = "firebirdsql/firebird"
    dialect = "firebird"
    probe_sql = "SELECT 1 FROM rdb$database;"
    versions = {v: {"image": f"firebirdsql/firebird:{v}"} for v in ("3", "4", "5")}

    def spec(self, version):
        spec = super().spec(version)
        spec["volume_path"] = DATA_DIR
        return spec

    def prepare(self, inst):
        super().prepare(inst)
        if inst.user.upper() == self.admin_user:
            raise EngineError(f"user '{inst.user}' is reserved by Firebird; choose another application account")

    def _db_file(self, inst):
        return f"{DATA_DIR}/{inst.database}.fdb"

    def environment(self, inst):
        # Users live in the security database outside the volume; the image re-applies these on every start
        return {
            "FIREBIRD_ROOT_PASSWORD": inst.admin_password,
            "FIREBIRD_USER": inst.user,
            "FIREBIRD_PASSWORD": inst.password,
            "FIREBIRD_DATABASE": f"{inst.database}.fdb",
            "FIREBIRD_DATABASE_DEFAULT_CHARSET": "UTF8",
        }

    def healthcheck(self, inst):
        return {
            "test": ["CMD-SHELL", f"bash -c '</dev/tcp/127.0.0.1/{self.port}' || exit 1"],
            "interval": "5s", "timeout": "5s", "retries": 30, "start_period": "5s",
        }

    def _isql(self, inst, admin, admin_password=None):
        user = self.admin_user if admin else inst.user
        pw = (admin_password or inst.admin_password) if admin else inst.password
        return ["isql", "-ch", "UTF8", "-user", user, "-password", pw, f"127.0.0.1/{self.port}:{self._db_file(inst)}"]

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        return ExecSpec([*self._isql(inst, admin, admin_password), "-q", "-bail", "-i", path])

    def shell(self, inst, *, admin):
        return ExecSpec(self._isql(inst, admin))

    def wrap_script(self, sql):
        # isql only auto-commits DDL
        return f"{sql.rstrip()}\nCOMMIT;\n"

    def bootstrap_sql(self, inst, admin_password_in_use):
        return ""  # the image creates the app user and makes it the owner of the database

    def database_label(self, inst):
        return self._db_file(inst)

    def jdbc_url(self, inst):
        return f"jdbc:firebird://localhost:{inst.port}/{self._db_file(inst)}?encoding=UTF8"
