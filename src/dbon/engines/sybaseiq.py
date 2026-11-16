from __future__ import annotations

from dbon.engines.base import Engine, EngineError, ExecSpec

DATA_DIR = "/home/iq/data"
SERVER = "dbon_iq"
IQ_USER = "iq"  # OS account that owns the installation; the server must not run as root
_RESERVED_USERS = {"DBA", "SYS", "PUBLIC", "DBO", "DIAGNOSTICS", "SA_DEBUG", "RS_SYSTABGROUP"}

# The image's bundled iqdemo database has an expired evaluation license, and its documented setup is
# interactive. Instead, the first start creates <database>.db through a throwaway utility server
# (a new database starts a new evaluation period), then every start runs iqsrv16 and stops it on
# `docker stop` (SIGTERM makes iqsrv16 checkpoint and shut down cleanly). Runs as root under
# `init: true` so the daemonized iqsrv16 is reaped; IQ commands run as the iq user.
_ENTRYPOINT = f"""\
set -u
D={DATA_DIR}
DB="$DBON_IQ_DB"
LOGS=/home/iq/iq/IQ-16_1/logfiles
as_iq() {{ su {IQ_USER} -s /bin/bash -c "cd /home/iq && . ./.bash_profile >/dev/null 2>&1 && cd $D && $1"; }}
stop_all() {{ pkill -TERM -x iqsrv16; while pgrep -x iqsrv16 >/dev/null; do sleep 1; done; }}

chown {IQ_USER}:{IQ_USER} "$D"
if [ ! -f "$D/.dbon_created" ]; then
  echo "[dbon] creating database $DB (IQ main $DBON_IQ_SIZE MB, temporary $DBON_IQ_TEMP_SIZE MB)"
  rm -f "$D/$DB".*
  cat > /tmp/dbon-create.sql <<EOF
CREATE DATABASE '$D/$DB.db'
  IQ PATH '$D/$DB.iq' IQ SIZE $DBON_IQ_SIZE
  TEMPORARY PATH '$D/$DB.iqtmp' TEMPORARY SIZE $DBON_IQ_TEMP_SIZE
  MESSAGE PATH '$D/$DB.iqmsg'
  COLLATION 'UTF8BIN'
  DBA USER 'DBA' DBA PASSWORD '$DBON_DBA_PASSWORD'
  MINIMUM PASSWORD LENGTH 1;
EOF
  chown {IQ_USER}:{IQ_USER} /tmp/dbon-create.sql
  as_iq 'start_iq -n dbon_util -su DBA,dbonutil -x "tcpip{{port=2639}}" -c 48m' || exit 1
  as_iq 'dbisql -nogui -onerror exit -c "uid=DBA;pwd=dbonutil;eng=dbon_util;dbn=utility_db;links=tcpip{{host=127.0.0.1;port=2639}}" /tmp/dbon-create.sql'
  rc=$?
  stop_all
  rm -f /tmp/dbon-create.sql
  if [ $rc -ne 0 ]; then
    echo "[dbon] CREATE DATABASE failed (exit code $rc)"
    exit 1
  fi
  touch "$D/.dbon_created"
fi

as_iq "start_iq -n {SERVER} -x 'tcpip{{port=2638}}' -c 48m $DBON_IQ_OPTS '$D/$DB.db'" 2>&1 | tee /tmp/dbon-start.out
if [ "${{PIPESTATUS[0]}}" -ne 0 ] || ! pgrep -x iqsrv16 >/dev/null; then
  if grep -q "No SYSAM License" /tmp/dbon-start.out; then
    echo "[dbon] The evaluation license of this database has expired, so the server cannot start."
    echo "[dbon] Recreate the instance (dbon rm, then dbon up) to create a new database and start a new evaluation period."
  fi
  exit 1
fi
PID=$(pgrep -x iqsrv16)
tail -n 0 -F "$(ls -t "$LOGS"/{SERVER}.*.srvlog | head -n 1)" &
stop() {{
  kill -TERM "$PID"
  while kill -0 "$PID" 2>/dev/null; do sleep 1; done
  exit 0
}}
trap stop TERM INT
while kill -0 "$PID" 2>/dev/null; do sleep 2 & wait $!; done
echo "[dbon] iqsrv16 exited"
exit 1
"""

_DBISQL = (
    "cd /home/iq && . ./.bash_profile >/dev/null 2>&1; "
    'exec dbisql -nogui -c "uid=$DBON_U;pwd=$DBON_P;dbn=$DBON_D;eng=' + SERVER
    + ';charset=utf-8;links=tcpip{host=127.0.0.1;port=2638}" "$@"'
)


class SybaseIQ(Engine):
    name = "sybaseiq"
    label = "SAP IQ (Sybase IQ)"
    aliases = ("iq", "sapiq", "sybase-iq", "sap-iq")
    port = 2638
    admin_user = "DBA"
    default_version = "16.1"
    base_image = "baeghaeun/sybase_iq"
    dialect = "sybaseiq"
    versions = {"16.1": {"image": "baeghaeun/sybase_iq:16.1"}}
    first_use_notice = (
        "Notice: SAP IQ runs from the community image baeghaeun/sybase_iq (not an official SAP image),\n"
        "which ships an evaluation copy of SAP IQ 16.1. Each new database starts a new evaluation period;\n"
        "once it ends the server no longer starts (\"No SYSAM License Available\") and the instance must be\n"
        "recreated with `dbon rm` and `dbon up`. By using SAP IQ through dbon you agree to SAP's license terms."
    )

    def spec(self, version):
        spec = super().spec(version)
        spec["volume_path"] = DATA_DIR
        return spec

    def prepare(self, inst):
        super().prepare(inst)
        if inst.user.upper() in _RESERVED_USERS:
            raise EngineError(f"user '{inst.user}' is reserved by SAP IQ; choose another application account")
        for key in ("password", "admin_password"):
            if ";" in getattr(inst, key):
                raise EngineError(f"SAP IQ passwords cannot contain ';' ({key})")

    def environment(self, inst):
        # sizes in MB; IQ dbspaces do not grow on their own. Override with --env, e.g. DBON_IQ_SIZE=2000
        return {
            "DBON_IQ_DB": inst.database,
            "DBON_DBA_PASSWORD": inst.admin_password,
            "DBON_IQ_SIZE": "500",
            "DBON_IQ_TEMP_SIZE": "200",
            "DBON_IQ_OPTS": "-iqmc 256 -iqtc 256",  # main/temporary cache (MB)
        }

    def service_extras(self, inst):
        # compose interpolates $VAR, so the script's shell variables must be escaped
        return {
            "entrypoint": ["bash", "-c", _ENTRYPOINT.replace("$", "$$")],
            "init": True,
            "stop_grace_period": "60s",
        }

    def healthcheck(self, inst):
        return {
            "test": ["CMD-SHELL", f"bash -c '</dev/tcp/127.0.0.1/{self.port}' || exit 1"],
            "interval": "5s", "timeout": "5s", "retries": 60, "start_period": "30s",
        }

    def _env(self, inst, admin, admin_password=None):
        env = {"DBON_D": inst.database, "LANG": "en_US.UTF-8"}  # dbisql reads and prints files in the JVM charset
        if admin:
            return {**env, "DBON_U": self.admin_user, "DBON_P": admin_password or inst.admin_password}
        return {**env, "DBON_U": inst.user, "DBON_P": inst.password}

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        return ExecSpec(["bash", "-c", _DBISQL, "dbisql", "-onerror", "exit", path], user=IQ_USER,
                        env=self._env(inst, admin, admin_password))

    def shell(self, inst, *, admin):
        return ExecSpec(["bash", "-c", _DBISQL, "dbisql"], user=IQ_USER, env=self._env(inst, admin))

    def bootstrap_sql(self, inst, admin_password_in_use):
        # The DBA password is set when the entrypoint creates the database. Both grants are idempotent.
        u, pw = inst.user, inst.password
        return (
            f'GRANT CONNECT TO {u} IDENTIFIED BY "{pw}";\n'
            f"GRANT ROLE SYS_AUTH_RESOURCE_ROLE TO {u};\n"
        )

    def jdbc_url(self, inst):
        return f"jdbc:sybase:Tds:localhost:{inst.port}?ServiceName={inst.database}&CHARSET=utf8"
