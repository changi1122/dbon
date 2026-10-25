from __future__ import annotations

from typing import Any

from dbon.engines.base import Engine, ExecSpec
from dbon.instance import Instance

# flavor "official": images built from oracle/docker-images (ORACLE_PWD, checkDBStatus.sh)
# flavor "gvenzl":   gvenzl/oracle-xe, gvenzl/oracle-free (ORACLE_PASSWORD, healthcheck.sh)
ORADATA = "/opt/oracle/oradata"


class Oracle(Engine):
    name = "oracle"
    label = "Oracle"
    aliases = ("ora",)
    port = 1521
    admin_user = "system"
    default_version = "19"
    dialect = "oracle"
    probe_sql = "SELECT 1 FROM dual;"
    versions = {
        "11": {"image": "gvenzl/oracle-xe:11", "flavor": "gvenzl", "service": "XE", "volume_path": "/u01/app/oracle/oradata"},
        # doctorkirk/oracle-19c creates a non-CDB database: connect to the SID service directly
        "19": {"image": "doctorkirk/oracle-19c:19.3", "flavor": "official", "service": "ORCL", "sid": "ORCL", "volume_path": ORADATA},
        "21": {"image": "gvenzl/oracle-xe:21-slim", "flavor": "gvenzl", "service": "XEPDB1", "volume_path": ORADATA},
        "23": {"image": "gvenzl/oracle-free:23-slim", "flavor": "gvenzl", "service": "FREEPDB1", "volume_path": ORADATA},
    }

    def prepare(self, inst: Instance) -> None:
        super().prepare(inst)
        spec = self.spec(inst.version)
        inst.extra.setdefault("flavor", spec["flavor"])
        inst.extra.setdefault("service", spec["service"])
        if "sid" in spec:
            inst.extra.setdefault("sid", spec["sid"])

    def environment(self, inst: Instance) -> dict[str, str]:
        if inst.extra["flavor"] == "official":
            return {
                "ORACLE_SID": inst.extra.get("sid", "ORCL"),
                "ORACLE_PWD": inst.admin_password,
                "ORACLE_CHARACTERSET": "AL32UTF8",
            }
        return {"ORACLE_PASSWORD": inst.admin_password}

    def healthcheck(self, inst: Instance) -> dict[str, Any]:
        if inst.extra["flavor"] == "official":
            test = ["CMD-SHELL", '"$$ORACLE_BASE/checkDBStatus.sh" >/dev/null || exit 1']
        else:
            test = ["CMD", "healthcheck.sh"]
        return {"test": test, "interval": "15s", "timeout": "10s", "retries": 10, "start_period": "60s"}

    def _connect(self, inst: Instance, admin: bool, admin_password: str | None = None) -> str:
        user = self.admin_user if admin else inst.user
        pw = (admin_password or inst.admin_password) if admin else inst.password
        return f'{user}/"{pw}"@//127.0.0.1:{self.port}/{inst.extra["service"]}'

    _env = {"NLS_LANG": "AMERICAN_AMERICA.AL32UTF8"}

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        return ExecSpec(["sqlplus", "-S", "-L", self._connect(inst, admin, admin_password), f"@{path}"], env=self._env)

    def shell(self, inst, *, admin):
        return ExecSpec(["sqlplus", "-L", self._connect(inst, admin)], env=self._env)

    def wrap_script(self, sql: str) -> str:
        header = (
            "WHENEVER SQLERROR EXIT FAILURE ROLLBACK\n"
            "WHENEVER OSERROR EXIT FAILURE ROLLBACK\n"
            "SET DEFINE OFF\nSET SQLBLANKLINES ON\nSET FEEDBACK OFF\nSET HEADING OFF\nSET PAGESIZE 0\n"
        )
        return f"{header}{sql.rstrip()}\nCOMMIT;\nEXIT\n"

    def bootstrap_sql(self, inst, admin_password_in_use):
        u, pw = inst.user.upper(), inst.password
        return f"""\
DECLARE
  n NUMBER;
BEGIN
  SELECT COUNT(*) INTO n FROM dba_users WHERE username = '{u}';
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER {u} IDENTIFIED BY "{pw}" DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS';
  ELSE
    EXECUTE IMMEDIATE 'ALTER USER {u} IDENTIFIED BY "{pw}" ACCOUNT UNLOCK';
  END IF;
END;
/
GRANT CONNECT, RESOURCE, CREATE VIEW, CREATE SEQUENCE, CREATE SYNONYM, CREATE PROCEDURE TO {u};
"""

    def database_label(self, inst):
        return f"{inst.extra['service']} (service name)"

    def jdbc_url(self, inst):
        return f"jdbc:oracle:thin:@//localhost:{inst.port}/{inst.extra['service']}"
