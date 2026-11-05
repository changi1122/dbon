from __future__ import annotations

from dbon import docker
from dbon.engines.base import Engine, EngineError, ExecSpec

INSTANCE_USER = "db2inst1"
# Accounts the image already owns; passwords of the app user are applied to the OS account.
_RESERVED_USERS = {"root", INSTANCE_USER, "db2fenc1"}
DB_NAME_MAX = 8  # Db2 limit

# The CLP keeps its connection per parent process, so connect and script must share this shell (no $(...)).
# Quoting the password: the CLP rejects characters such as "!" otherwise.
_CONNECT = (
    'source "$HOME/sqllib/db2profile"; '
    'log=$(mktemp); '
    'db2 "connect to $DBON_D user $DBON_U using \\"$DBON_P\\"" >"$log"; rc=$?; '
    '[ $rc -ge 4 ] && cat "$log"; rm -f "$log"; '
    '[ $rc -ge 4 ] && exit $rc; '
)
# CLP exit codes: 1 = no rows, 2 = warning, 4 = SQL error, 8 = CLP error
_RUN = _CONNECT + 'db2 "$@"; rc=$?; db2 terminate >/dev/null; [ $rc -ge 4 ] && exit $rc; exit 0'
_SHELL = _CONNECT + 'db2 -t'

# Db2 authenticates against OS accounts, which live in the container and not in the data volume.
_OS_USER = (
    'id -u "$DBON_U" >/dev/null 2>&1 || useradd -M -s /sbin/nologin "$DBON_U" || exit 1; '
    'printf "%s:%s\\n" "$DBON_U" "$DBON_P" | chpasswd'
)


class Db2(Engine):
    name = "db2"
    label = "IBM Db2"
    port = 50000
    admin_user = INSTANCE_USER
    default_version = "11.5.8.0"
    base_image = "ibmcom/db2"
    dialect = "db2"
    probe_sql = "VALUES 1;"
    versions = {v: {"image": f"ibmcom/db2:{v}"} for v in ("11.5.4.0", "11.5.5.1", "11.5.8.0")}
    ready_marker = "Setup has completed."
    first_use_notice = (
        "Notice: Db2 runs under the IBM Db2 Community Edition license (https://hub.docker.com/r/ibmcom/db2).\n"
        "dbon sets LICENSE=accept for the container; by using Db2 through dbon you agree to that license."
    )

    def spec(self, version):
        spec = super().spec(version)
        spec["volume_path"] = "/database"
        return spec

    def prepare(self, inst):
        super().prepare(inst)
        if len(inst.database) > DB_NAME_MAX:
            raise EngineError(f"Db2 database names are limited to {DB_NAME_MAX} characters: {inst.database}")
        if inst.user.lower() in _RESERVED_USERS:
            raise EngineError(f"user '{inst.user}' is reserved by the Db2 image; choose another application account")

    def environment(self, inst):
        return {
            "LICENSE": "accept",
            "DB2INST1_PASSWORD": inst.admin_password,
            "DBNAME": inst.database,
            "TO_CREATE_SAMPLEDB": "false",
            "ARCHIVE_LOGS": "false",
        }

    def service_extras(self, inst):
        return {"privileged": True}  # required by the image (kernel parameters, /database remount)

    def healthcheck(self, inst):
        return {
            "test": ["CMD-SHELL", f"bash -c '</dev/tcp/127.0.0.1/{self.port}' || exit 1"],
            "interval": "10s", "timeout": "5s", "retries": 30, "start_period": "120s",
        }

    def _env(self, inst, admin, admin_password=None):
        env = {"DBON_D": inst.database, "DB2CODEPAGE": "1208"}  # the CLP would otherwise mangle Korean
        if admin:
            return {**env, "DBON_U": self.admin_user, "DBON_P": admin_password or inst.admin_password}
        return {**env, "DBON_U": inst.user.lower(), "DBON_P": inst.password}

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        return ExecSpec(["bash", "-c", _RUN, "db2", "-stf", path], user=INSTANCE_USER,
                        env=self._env(inst, admin, admin_password))

    def shell(self, inst, *, admin):
        return ExecSpec(["bash", "-c", _SHELL], user=INSTANCE_USER, env=self._env(inst, admin))

    def on_ready(self, inst):
        return [ExecSpec(["bash", "-c", _OS_USER], user="0",
                         env={"DBON_U": inst.user.lower(), "DBON_P": inst.password})]

    def bootstrap_sql(self, inst, admin_password_in_use):
        u = inst.user
        return (
            f"GRANT CONNECT, CREATETAB, BINDADD, IMPLICIT_SCHEMA ON DATABASE TO USER {u};\n"
            f"GRANT USE OF TABLESPACE USERSPACE1 TO USER {u};\n"
        )

    def jdbc_url(self, inst):
        return f"jdbc:db2://localhost:{inst.port}/{inst.database}"

    def setup_finished(self, inst, started_at):
        # The image restarts the server during setup; previous logs persist across restarts
        proc = docker.run(["logs", "--since", started_at, inst.container], check=False)
        return self.ready_marker in proc.stdout + proc.stderr
