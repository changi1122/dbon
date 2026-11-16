from __future__ import annotations

import re

from dbon import docker
from dbon.engines.base import Engine, EngineError, ExecSpec

SID = "HXE"
INSTANCE = "90"
TENANT = "HXE"  # HANA express ships one tenant database; creating more needs far more memory
HOSTNAME = "hxehost"  # the installation is bound to the host name
HDBSQL = f"/usr/sap/{SID}/HDB{INSTANCE}/exe/hdbsql"
INSTALLER_VERSION = "2.00.033.00.20180925.2"  # the release muxob/hana-express installs (2.0 SPS03)
INSTALLER_URL = f"https://d149oh3iywgk04.cloudfront.net/hanaexpress/2.0/{INSTALLER_VERSION}/tar/linuxx86_64/hxe.tgz"
# Shared by all hana instances, so only the first `dbon up hana` downloads the 1.5 GB installer
CACHE_VOLUME = "dbon-hana-installer"
_RESERVED_USERS = {"SYSTEM", "SYS"}
_ADMIN_PW_RULE = re.compile(r"^(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9]).{8,}$")  # installer's master password rule
_USER_PW_RULE = re.compile(r"^(?=.*[a-z]).{6,}$")  # the loosest policy HANA accepts (see bootstrap_sql)

# The image's /start.sh downloads and installs HANA on the first run and then exits; later runs start
# HDB and block on `cat`, with no shutdown handling. This wrapper installs and starts in the same run
# and stops HDB on `docker stop`. Installation lives in the volumes (/hana/shared, /usr/sap), but the
# OS accounts and a few files under /etc do not, so they are saved in the volume and restored when the
# container is recreated.
_ENTRYPOINT = f"""\
set -u
CACHE=/installer
TGZ="$CACHE/hxe-$DBON_INSTALLER_VERSION.tgz"
MARK=/hana/shared/.dbon_installed
ETC=/hana/shared/.dbon_etc
log() {{ echo "[dbon] $*"; }}

if [ ! -f "$MARK" ]; then
  if ! gzip -t "$TGZ" 2>/dev/null; then
    log "downloading the SAP HANA express installer (1.5 GB) into volume {CACHE_VOLUME}"
    PART=$(mktemp "$TGZ.XXXX")
    wget -q --referer=https://go.sap.com/ -O "$PART" "$DBON_INSTALLER_URL" && gzip -t "$PART" || {{ rm -f "$PART"; log "download failed"; exit 1; }}
    mv -f "$PART" "$TGZ"
  fi
  log "installing SAP HANA express (about 10 minutes)"
  rm -rf /hxeinstall && mkdir /hxeinstall && tar -xzf "$TGZ" -C /hxeinstall || exit 1
  /hxeinstall/setup_hxe.sh <<EOF | tee /tmp/dbon-install.log
/hxeinstall/HANA_EXPRESS_20
{SID}
{INSTANCE}

$DBON_MASTER_PASSWORD
$DBON_MASTER_PASSWORD
y
EOF
  rm -rf /hxeinstall
  grep -q "Server Installation...(OK)" /tmp/dbon-install.log || {{ log "installation failed"; exit 1; }}
  mkdir -p "$ETC"
  for f in passwd group shadow; do grep -E '^(hxeadm|sapadm|sapsys|hxeshm):' /etc/$f > "$ETC/$f"; done
  tar -cf "$ETC/files.tar" /etc/security/limits.d/99-sapsys.conf /etc/pam.d/sapstartsrv /etc/init.d/sapinit 2>/dev/null
  touch "$MARK"
elif ! id hxeadm >/dev/null 2>&1; then
  log "restoring OS accounts of the installation (container was recreated)"
  for f in group passwd shadow; do cat "$ETC/$f" >> /etc/$f; done
  tar -xf "$ETC/files.tar" -C / 2>/dev/null
  # IPC directory the daemon refuses to start without
  mkdir -p /var/lib/hdb/{SID} && chown hxeadm:sapsys /var/lib/hdb/{SID}
fi

su - hxeadm -c "HDB start" || exit 1
stop() {{
  log "stopping HDB"
  su - hxeadm -c "HDB stop"
  exit 0
}}
trap stop TERM INT
while :; do sleep 5 & wait $!; done
"""

_HDBSQL = f'exec {HDBSQL} -n 127.0.0.1:{{port}} -d {TENANT} -u "$DBON_U" -p "$DBON_P" -B UTF8 -resultencoding UTF8 "$@"'


class Hana(Engine):
    name = "hana"
    label = "SAP HANA, express edition"
    aliases = ("hxe", "saphana", "sap-hana", "hana-express")
    port = 39015  # SQL port of the HXE tenant
    admin_user = "SYSTEM"
    default_version = "2.0"
    base_image = "muxob/hana-express"
    dialect = "hana"
    probe_sql = "SELECT 1 FROM DUMMY;"
    versions = {"2.0": {"image": "muxob/hana-express:latest"}}
    first_use_notice = (
        "Notice: SAP HANA runs from the community image muxob/hana-express (not an official SAP image).\n"
        "The first start downloads the SAP HANA, express edition 2.0 SPS03 installer (1.5 GB) from SAP's CDN\n"
        f"into the shared volume {CACHE_VOLUME} and installs it, which takes about 10 minutes and around 10 GB\n"
        "of memory. By using SAP HANA, express edition through dbon you agree to SAP's license for it\n"
        "(SAP HANA, express edition is free for development and productive use up to 32 GB of memory)."
    )

    def spec(self, version):
        spec = super().spec(version)
        spec["volume_path"] = "/hana/shared"
        return spec

    def prepare(self, inst):
        super().prepare(inst)
        inst.database = TENANT
        if inst.user.upper() in _RESERVED_USERS or inst.user.upper().startswith("_SYS"):
            raise EngineError(f"user '{inst.user}' is reserved by SAP HANA; choose another application account")
        hint = "Set engines.hana in ~/.dbon/config.yaml or pass the option to `dbon up`."
        if not _ADMIN_PW_RULE.match(inst.admin_password):
            raise EngineError(
                "SAP HANA needs an admin password of at least 8 characters with an uppercase letter, "
                f"a lowercase letter, and a digit (--admin-password). {hint}"
            )
        if not _USER_PW_RULE.match(inst.password):
            raise EngineError(
                f"SAP HANA needs a password of at least 6 characters with a lowercase letter (--password). {hint}"
            )

    def environment(self, inst):
        return {
            "DBON_MASTER_PASSWORD": inst.admin_password,
            "DBON_INSTALLER_URL": INSTALLER_URL,
            "DBON_INSTALLER_VERSION": INSTALLER_VERSION,
        }

    def service_extras(self, inst):
        # compose interpolates $VAR, so the script's shell variables must be escaped
        return {
            "entrypoint": ["bash", "-c", _ENTRYPOINT.replace("$", "$$")],
            "hostname": HOSTNAME,
            "init": True,
            "stop_grace_period": "180s",
        }

    def healthcheck(self, inst):
        # The installer starts the database long before it finishes, so wait for the dbon marker as well
        return {
            "test": ["CMD-SHELL", f"test -f /hana/shared/.dbon_installed && bash -c '</dev/tcp/127.0.0.1/{self.port}' || exit 1"],
            "interval": "10s", "timeout": "5s", "retries": 30, "start_period": "1800s",
        }

    def compose(self, inst):
        doc = super().compose(inst)
        svc = doc["services"]["db"]
        # /usr/sap holds the instance profile and the hxeadm home; the installer cache is shared
        svc["volumes"] += ["sap:/usr/sap", "installer:/installer"]
        doc["volumes"]["sap"] = {"labels": {"dbon.managed": "true", "dbon.instance": inst.name}}
        doc["volumes"]["installer"] = {"external": True, "name": CACHE_VOLUME}
        return doc

    def before_start(self, inst):
        # external volume: compose neither creates it nor removes it on `down -v`
        docker.run(["volume", "create", "--label", "dbon.managed=true", CACHE_VOLUME])

    def _env(self, inst, admin, admin_password=None):
        if admin:
            return {"DBON_U": self.admin_user, "DBON_P": admin_password or inst.admin_password}
        return {"DBON_U": inst.user, "DBON_P": inst.password}

    def _cmd(self):
        return ["bash", "-c", _HDBSQL.format(port=self.port), "hdbsql"]

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        # No -E: with it, hdbsql stops at the first *warning* and exits 0, silently skipping the rest.
        # Without it, errors do not stop the script either, so runner detects them in the output.
        return ExecSpec([*self._cmd(), "-x", "-I", path], env=self._env(inst, admin, admin_password))

    def shell(self, inst, *, admin):
        return ExecSpec([*self._cmd(), "-A"], env=self._env(inst, admin))

    def bootstrap_sql(self, inst, admin_password_in_use):
        u, pw = inst.user, inst.password
        return f"""\
ALTER SYSTEM ALTER CONFIGURATION ('indexserver.ini', 'DATABASE') SET
  ('password policy', 'minimal_password_length') = '6',
  ('password policy', 'password_layout') = 'a',
  ('password policy', 'force_first_password_change') = 'false',
  ('password policy', 'last_used_passwords') = '0'
  WITH RECONFIGURE;
DO BEGIN
  DECLARE n INT;
  SELECT COUNT(*) INTO n FROM USERS WHERE USER_NAME = UPPER('{u}');
  IF :n = 0 THEN
    EXEC 'CREATE USER {u} PASSWORD "{pw}" NO FORCE_FIRST_PASSWORD_CHANGE';
  ELSE
    EXEC 'ALTER USER {u} PASSWORD "{pw}" NO FORCE_FIRST_PASSWORD_CHANGE';
  END IF;
END;
ALTER USER {u} DISABLE PASSWORD LIFETIME;
"""  # the installer already disables SYSTEM's password lifetime (and SYSTEM may not alter that for itself)

    def database_label(self, inst):
        return TENANT

    def jdbc_url(self, inst):
        return f"jdbc:sap://localhost:{inst.port}/"
