from __future__ import annotations

from dbon.engines.base import Engine, ExecSpec

# Newer images ship mssql-tools18 (needs -C to trust the self-signed cert); older 2019 builds only mssql-tools.
_SQLCMD = (
    'S=/opt/mssql-tools18/bin/sqlcmd; X=-C; '
    '[ -x "$S" ] || { S=/opt/mssql-tools/bin/sqlcmd; X=; }; '
    'exec "$S" $X -S 127.0.0.1 -U "$DBON_U" -P "$DBON_P" -d "$DBON_D" -I "$@"'
)


class MSSQL(Engine):
    name = "mssql"
    label = "SQL Server"
    aliases = ("ms-sql", "sqlserver", "sql-server")
    port = 1433
    admin_user = "sa"
    default_version = "2022"
    base_image = "mcr.microsoft.com/mssql/server"
    dialect = "mssql"
    probe_sql = "SELECT 1;\nGO\n"
    versions = {v: {"image": f"mcr.microsoft.com/mssql/server:{v}-latest"} for v in ("2019", "2022", "2025")}

    def spec(self, version):
        spec = super().spec(version)
        spec["volume_path"] = "/var/opt/mssql"
        return spec

    def environment(self, inst):
        return {"ACCEPT_EULA": "Y", "MSSQL_PID": "Developer", "MSSQL_SA_PASSWORD": inst.admin_password}

    def _env(self, inst, admin, admin_password=None):
        if admin:
            return {"DBON_U": self.admin_user, "DBON_P": admin_password or inst.admin_password, "DBON_D": "master"}
        return {"DBON_U": inst.user, "DBON_P": inst.password, "DBON_D": inst.database}

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        return ExecSpec(["bash", "-c", _SQLCMD, "sqlcmd", "-b", "-f", "65001", "-i", path], env=self._env(inst, admin, admin_password))

    def shell(self, inst, *, admin):
        return ExecSpec(["bash", "-c", _SQLCMD, "sqlcmd"], env=self._env(inst, admin))

    def bootstrap_sql(self, inst, admin_password_in_use):
        u, pw, db = inst.user, inst.password, inst.database
        return f"""\
IF DB_ID(N'{db}') IS NULL CREATE DATABASE [{db}];
GO
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'{u}')
  CREATE LOGIN [{u}] WITH PASSWORD = N'{pw}', CHECK_POLICY = OFF, DEFAULT_DATABASE = [{db}];
ELSE
  ALTER LOGIN [{u}] WITH PASSWORD = N'{pw}';
GO
USE [{db}];
GO
IF USER_ID(N'{u}') IS NULL CREATE USER [{u}] FOR LOGIN [{u}];
ALTER ROLE db_owner ADD MEMBER [{u}];
GO
"""

    def jdbc_url(self, inst):
        return (
            f"jdbc:sqlserver://localhost:{inst.port};databaseName={inst.database};"
            "encrypt=true;trustServerCertificate=true"
        )
