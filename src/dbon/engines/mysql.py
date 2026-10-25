from __future__ import annotations

from dbon.engines.base import Engine, ExecSpec


class MySQL(Engine):
    name = "mysql"
    label = "MySQL"
    port = 3306
    admin_user = "root"
    default_version = "8.4"
    base_image = "mysql"
    dialect = "mysql"
    client = "mysql"
    client_opts = "--default-character-set=utf8mb4"
    jdbc_scheme = "mysql"
    versions = {v: {"image": f"mysql:{v}"} for v in ("5.7", "8.0", "8.4", "9")}

    def spec(self, version):
        spec = super().spec(version)
        spec["volume_path"] = "/var/lib/mysql"
        return spec

    def environment(self, inst):
        return {"MYSQL_ROOT_PASSWORD": inst.admin_password, "MYSQL_ROOT_HOST": "%"}

    def command(self, inst):
        return ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci"]

    def healthcheck(self, inst):
        return {
            "test": ["CMD-SHELL", "mysqladmin ping -h 127.0.0.1 -uroot -p$$MYSQL_ROOT_PASSWORD --silent"],
            "interval": "5s", "timeout": "5s", "retries": 30, "start_period": "20s",
        }

    def _creds(self, inst, admin, admin_password=None):
        if admin:
            return self.admin_user, admin_password or inst.admin_password, ""
        return inst.user, inst.password, inst.database

    def exec_sql(self, inst, path, *, admin, admin_password=None):
        user, pw, db = self._creds(inst, admin, admin_password)
        script = f"exec {self.client} -h127.0.0.1 -P{self.port} -u{user} {self.client_opts} {db} < {path}"
        return ExecSpec(["sh", "-c", script], env={"MYSQL_PWD": pw})

    def shell(self, inst, *, admin):
        user, pw, db = self._creds(inst, admin)
        cmd = [self.client, "-h127.0.0.1", f"-P{self.port}", f"-u{user}", *self.client_opts.split()]
        return ExecSpec(cmd + ([db] if db else []), env={"MYSQL_PWD": pw})

    def bootstrap_sql(self, inst, admin_password_in_use):
        u, pw, db = inst.user, inst.password, inst.database
        return f"""\
CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '{u}'@'%' IDENTIFIED BY '{pw}';
ALTER USER '{u}'@'%' IDENTIFIED BY '{pw}';
GRANT ALL PRIVILEGES ON `{db}`.* TO '{u}'@'%';
FLUSH PRIVILEGES;
"""

    def jdbc_url(self, inst):
        return f"jdbc:{self.jdbc_scheme}://localhost:{inst.port}/{inst.database}"


class MariaDB(MySQL):
    name = "mariadb"
    label = "MariaDB"
    aliases = ("maria",)
    default_version = "11.4"
    base_image = "mariadb"
    dialect = "mariadb"
    client = "mariadb"
    # password comes via MYSQL_PWD, which the 11.x client counts as "passwordless" and warns about
    client_opts = "--default-character-set=utf8mb4 --skip-ssl-verify-server-cert"
    jdbc_scheme = "mariadb"
    versions = {v: {"image": f"mariadb:{v}"} for v in ("10.6", "10.11", "11.4", "11.8")}

    def environment(self, inst):
        return {"MARIADB_ROOT_PASSWORD": inst.admin_password, "MARIADB_ROOT_HOST": "%"}

    def healthcheck(self, inst):
        return {
            "test": ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"],
            "interval": "5s", "timeout": "5s", "retries": 30, "start_period": "20s",
        }
