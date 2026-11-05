from __future__ import annotations

from dbon.engines.base import Engine, EngineError, ExecSpec

ALTIBASE_HOME = "/root/altibase_home"
# Baked into the image with the prebuilt database; bootstrap replaces it.
IMAGE_SYS_PASSWORD = "manager"
DB_NAME = "mydb"  # the image ships a prebuilt database, so DB_NAME and DB_CHARSET cannot be chosen
_RESERVED_USERS = {"SYS", "SYSTEM_"}

# Replaces the image's docker-entrypoint.sh, whose checkServer exits with code -19 after any
# `docker stop` (the container never comes back). Starts the server and shuts it down on `docker stop`.
# `server start` logs a harmless ERR-4102E once the sys password has changed.
_ENTRYPOINT = f"""\
cd /root
. ./set_altibase.env
export ALTIBASE_MEM_MAX_DB_SIZE="$MEM_MAX_DB_SIZE"
stop() {{
  for pw in "$DBON_SYS_PASSWORD" {IMAGE_SYS_PASSWORD}; do
    printf 'shutdown immediate;\\nquit\\n' | isql -u sys -p "$pw" -sysdba -noprompt -silent >/tmp/dbon-stop.out 2>&1
    grep -q 'ERR-' /tmp/dbon-stop.out || break
  done
  exit 0
}}
trap stop TERM INT
server start
sleep infinity &
wait $!
"""

_ISQL = (
    ". /root/set_altibase.env >/dev/null 2>&1; "
    'exec isql -s 127.0.0.1 -port "$ALTIBASE_PORT_NO" -silent -NLS_USE UTF8 -u "$DBON_U" -p "$DBON_P" "$@"'
)


class Altibase(Engine):
    name = "altibase"
    label = "Altibase A+ Edition"
    aliases = ("alti",)
    port = 20300
    admin_user = "sys"
    default_version = "7.3"
    base_image = "altibase/a_plus_edition"
    dialect = "altibase"
    probe_sql = "SELECT 1 FROM dual;"
    versions = {"7.3": {"image": "altibase/a_plus_edition:7.3"}}
    first_use_notice = (
        "Notice: Altibase A+ Edition is licensed for NON-COMMERCIAL use only "
        f"(see {ALTIBASE_HOME}/conf/Altibase-A+Edition-EULA.txt in the image).\n"
        "By using Altibase through dbon you agree to that license."
    )

    def spec(self, version):
        spec = super().spec(version)
        spec["volume_path"] = f"{ALTIBASE_HOME}/dbs"
        return spec

    def prepare(self, inst):
        super().prepare(inst)
        if inst.user.upper() in _RESERVED_USERS:
            raise EngineError(f"user '{inst.user}' is reserved by Altibase; choose another application account")
        inst.database = DB_NAME

    def environment(self, inst):
        return {"DBON_SYS_PASSWORD": inst.admin_password}

    def service_extras(self, inst):
        # compose interpolates $VAR, so the script's shell variables must be escaped
        return {
            "entrypoint": ["bash", "-c", _ENTRYPOINT.replace("$", "$$")],
            "stop_grace_period": "60s",
        }

    def healthcheck(self, inst):
        return {
            "test": ["CMD-SHELL", f"bash -c '</dev/tcp/127.0.0.1/{self.port}' || exit 1"],
            "interval": "5s", "timeout": "5s", "retries": 30, "start_period": "10s",
        }

    def compose(self, inst):
        # Log files and log anchors live outside dbs/, and the database cannot open without them
        doc = super().compose(inst)
        doc["services"]["db"]["volumes"].append(f"logs:{ALTIBASE_HOME}/logs")
        doc["volumes"]["logs"] = {"labels": {"dbon.managed": "true", "dbon.instance": inst.name}}
        return doc

    def probe_passwords(self, inst):
        return [inst.admin_password] if inst.bootstrapped else [IMAGE_SYS_PASSWORD, inst.admin_password]

    def _env(self, inst, admin, admin_password=None):
        if admin:
            return {"DBON_U": self.admin_user, "DBON_P": admin_password or inst.admin_password}
        return {"DBON_U": inst.user, "DBON_P": inst.password}

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        return ExecSpec(["bash", "-c", _ISQL, "isql", "-f", path], env=self._env(inst, admin, admin_password))

    def shell(self, inst, *, admin):
        return ExecSpec(["bash", "-c", _ISQL, "isql"], env=self._env(inst, admin))

    def wrap_script(self, sql):
        return f"{sql.rstrip()}\nquit\n"

    def bootstrap_sql(self, inst, admin_password_in_use):
        u, pw = inst.user, inst.password
        lines = f"""\
BEGIN
  EXECUTE IMMEDIATE 'CREATE USER {u} IDENTIFIED BY "{pw}"';
EXCEPTION WHEN OTHERS THEN
  EXECUTE IMMEDIATE 'ALTER USER {u} IDENTIFIED BY "{pw}"';
END;
/
"""
        if admin_password_in_use != inst.admin_password:
            lines += f'ALTER USER sys IDENTIFIED BY "{inst.admin_password}";\n'
        return lines

    def jdbc_url(self, inst):
        return f"jdbc:Altibase://localhost:{inst.port}/{DB_NAME}"
