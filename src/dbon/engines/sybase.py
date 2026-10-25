from __future__ import annotations

from dbon.engines.base import Engine, ExecSpec

# Password baked into the datagrip/sybase image's master device; bootstrap replaces it.
IMAGE_SA_PASSWORD = "myPassword"
SERVER = "MYSYBASE"

# Replaces the image's /entrypoint.sh, which creates the login/db with sa=myPassword on every start
# (racing our bootstrap) and has no working shutdown. Runs ASE in the background and shuts it down
# cleanly on `docker stop`.
_ENTRYPOINT = f"""\
source /opt/sybase/SYBASE.sh
stop() {{
  for pw in "$DBON_SA_PASSWORD" {IMAGE_SA_PASSWORD}; do
    printf 'shutdown\\ngo\\n' | isql -Usa -P"$pw" -S{SERVER} >/dev/null 2>&1 && break
  done
  wait "$PID"
  exit 0
}}
trap stop TERM INT
/opt/sybase/ASE-16_0/install/RUN_{SERVER} &
PID=$!
wait "$PID"
"""

_ISQL = (
    "source /opt/sybase/SYBASE.sh >/dev/null; "
    f'exec isql -U"$DBON_U" -P"$DBON_P" -S{SERVER} -D"$DBON_D" -J utf8 -w 250 "$@"'
)

# extra space (MB) added to the master device for the user database
DB_SIZE_MB = 200


class Sybase(Engine):
    name = "sybase"
    label = "SAP ASE (Sybase)"
    aliases = ("ase", "sybase-ase")
    port = 5000
    admin_user = "sa"
    default_version = "16.0"
    dialect = "sybase"
    probe_sql = "select 1\ngo\n"
    versions = {"16.0": {"image": "datagrip/sybase:16.0", "volume_path": "/opt/sybase/data"}}

    def environment(self, inst):
        return {"DBON_SA_PASSWORD": inst.admin_password}

    def service_extras(self, inst):
        # compose interpolates $VAR, so the script's shell variables must be escaped
        return {
            "entrypoint": ["bash", "-c", _ENTRYPOINT.replace("$", "$$")],
            "stop_grace_period": "60s",
        }

    def healthcheck(self, inst):
        return {
            "test": ["CMD-SHELL", f"bash -c '</dev/tcp/127.0.0.1/{self.port}' || exit 1"],
            "interval": "10s", "timeout": "5s", "retries": 30, "start_period": "30s",
        }

    def probe_passwords(self, inst):
        return [inst.admin_password] if inst.bootstrapped else [IMAGE_SA_PASSWORD, inst.admin_password]

    def _env(self, inst, admin, admin_password=None):
        if admin:
            return {"DBON_U": self.admin_user, "DBON_P": admin_password or inst.admin_password, "DBON_D": "master"}
        return {"DBON_U": inst.user, "DBON_P": inst.password, "DBON_D": inst.database}

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        return ExecSpec(["bash", "-c", _ISQL, "isql", "--retserverror", "-i", path],
                        env=self._env(inst, admin, admin_password))

    def shell(self, inst, *, admin):
        return ExecSpec(["bash", "-c", _ISQL, "isql"], env=self._env(inst, admin))

    def wrap_script(self, sql):
        # isql only sends a batch when it sees "go"; a trailing batch without one is silently dropped
        lines = [line.strip().lower() for line in sql.strip().splitlines()]
        return sql if lines and lines[-1] == "go" else f"{sql.rstrip()}\ngo\n"

    def bootstrap_sql(self, inst, admin_password_in_use):
        u, pw, db = inst.user, inst.password, inst.database
        lines = f"""\
use master
go
if db_id('{db}') is null disk resize name = 'master', size = '{DB_SIZE_MB}m'
go
if db_id('{db}') is null create database {db} on master = '{DB_SIZE_MB}m'
go
exec sp_dboption {db}, 'trunc log on chkpt', true
go
exec sp_dboption {db}, 'select into/bulkcopy/pllsort', true
go
exec sp_dboption {db}, 'ddl in tran', true
go
exec sp_dboption {db}, 'allow nulls by default', true
go
if not exists (select 1 from master..syslogins where name = '{u}')
  exec('create login {u} with password "{pw}" default database {db}')
go
use {db}
go
if user_id('{u}') is null exec sp_adduser '{u}', '{u}', null
go
grant create table to {u}
go
grant create view to {u}
go
grant create procedure to {u}
go
grant create default to {u}
go
grant create rule to {u}
go
use master
go
"""
        if admin_password_in_use != inst.admin_password:
            lines += f"exec sp_password '{admin_password_in_use}', '{inst.admin_password}', sa\ngo\n"
        return lines

    def jdbc_url(self, inst):
        return f"jdbc:sybase:Tds:localhost:{inst.port}/{inst.database}?charset=utf8"
