from __future__ import annotations

from dbon import docker
from dbon.engines.base import Engine, ExecSpec

# Data directory differs per image (CUBRID_DATABASES env); used when the image cannot be inspected.
_FALLBACK_DATA = {"11.0": "/var/lib/cubrid"}
_DEFAULT_DATA = "/home/cubrid/CUBRID/databases"


class Cubrid(Engine):
    name = "cubrid"
    label = "CUBRID"
    port = 33000  # broker
    admin_user = "dba"
    default_version = "11.4"
    base_image = "cubrid/cubrid"
    dialect = "cubrid"
    probe_sql = "SELECT 1 FROM db_root;"
    versions = {v: {"image": f"cubrid/cubrid:{v}"} for v in ("11.0", "11.2", "11.3", "11.4")}

    def prepare(self, inst):
        if "volume_path" not in inst.extra:
            if not docker.image_exists(inst.image):
                docker.pull(inst.image)
            path = docker.image_env(inst.image).get("CUBRID_DATABASES")
            inst.extra["volume_path"] = path or _FALLBACK_DATA.get(inst.version, _DEFAULT_DATA)

    def environment(self, inst):
        # en_US.utf8: plain en_US would create an iso88591 database
        return {"CUBRID_DB": inst.database, "CUBRID_LOCALE": "en_US.utf8"}

    def service_extras(self, inst):
        return {"privileged": True}  # 11.4+ adjusts kernel parameters on start

    def healthcheck(self, inst):
        return {
            "test": ["CMD-SHELL", "cubrid service status | grep -q 'running' || exit 1"],
            "interval": "10s", "timeout": "10s", "retries": 10, "start_period": "30s",
        }

    def probe_passwords(self, inst):
        # The official image never applies a dba password; bootstrap sets it.
        return [inst.admin_password] if inst.bootstrapped else ["", inst.admin_password]

    def _csql(self, inst, admin, admin_password=None):
        if admin:
            user = self.admin_user
            pw = inst.admin_password if admin_password is None else admin_password
        else:
            user, pw = inst.user, inst.password
        return ["csql", "-u", user, "-p", pw, inst.database]

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        return ExecSpec([*self._csql(inst, admin, admin_password), "-i", path], user="cubrid")

    def shell(self, inst, *, admin):
        return ExecSpec(self._csql(inst, admin), user="cubrid")

    def wrap_script(self, sql):
        return f"{sql.rstrip()}\nCOMMIT;\n"

    def bootstrap_sql(self, inst, admin_password_in_use):
        u, pw = inst.user, inst.password
        lines = [
            f"CREATE USER {u} PASSWORD '{pw}';",
        ]
        if admin_password_in_use != inst.admin_password:
            lines.append(f"ALTER USER dba PASSWORD '{inst.admin_password}';")
        return "\n".join(lines) + "\n"

    def jdbc_url(self, inst):
        return f"jdbc:cubrid:localhost:{inst.port}:{inst.database}:::?charset=utf-8"
