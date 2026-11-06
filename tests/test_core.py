from datetime import date, datetime
from decimal import Decimal

import pytest
import yaml

from dbon import cli, config, engines, instance, runner
from dbon.dummy import DIALECTS, Dialect, render
from dbon.dummy.data import generate
from dbon.instance import Instance


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DBON_HOME", str(tmp_path))
    return tmp_path


def make(engine_name: str, version: str | None = None, **kw) -> Instance:
    engine, ver = engines.parse_target(f"{engine_name}:{version}" if version else engine_name)
    s = config.resolve_settings(config.load_config(), engine.name, ver)
    inst = Instance(name="t", engine=engine.name, version=ver, image=engine.spec(ver)["image"], port=12345,
                    user=s["user"], password=s["password"], admin_password=s["admin_password"],
                    database=s["database"], **kw)
    if engine.name == "cubrid":
        inst.extra["volume_path"] = "/var/lib/cubrid"
    engine.prepare(inst)
    return inst


# ---- config ------------------------------------------------------------------
def test_settings_precedence():
    cfg = {
        "defaults": {"user": "a", "password": "p1"},
        "engines": {"mysql": {"password": "p2", "versions": {"8.0": {"password": "p3"}}}},
    }
    assert config.resolve_settings(cfg, "postgres", "18")["password"] == "p1"
    assert config.resolve_settings(cfg, "mysql", "8.4")["password"] == "p2"
    assert config.resolve_settings(cfg, "mysql", "8.0")["password"] == "p3"
    assert config.resolve_settings(cfg, "mysql", "8.0", {"password": "cli", "user": None})["password"] == "cli"
    assert config.resolve_settings(cfg, "mysql", "8.0")["user"] == "a"


def test_default_config_file_created(home):
    cfg = config.load_config()
    assert (home / "config.yaml").exists()
    assert config.resolve_settings(cfg, "oracle", "19")["admin_password"] == "DBon0000!"
    assert config.resolve_settings(cfg, "mssql", "2022")["admin_password"] == "DBon0000!"


@pytest.mark.parametrize("key,value", [("user", "1abc"), ("database", "a-b"), ("password", "a'b"), ("admin_password", "a b")])
def test_settings_validation(key, value):
    with pytest.raises(config.ConfigError):
        config.resolve_settings({"defaults": {key: value}}, "mysql", "8.4")


# ---- engines -----------------------------------------------------------------
def test_parse_target_aliases():
    assert engines.parse_target("pg")[0].name == "postgres"
    assert engines.parse_target("ms-sql:2019") == (engines.get("mssql"), "2019")
    assert engines.parse_target("maria")[1] == "11.4"
    with pytest.raises(engines.EngineError):
        engines.parse_target("nosuchdb")
    with pytest.raises(engines.EngineError):
        engines.get("oracle").spec("8")


def test_custom_tag():
    assert engines.get("mysql").spec("8.0.36")["image"] == "mysql:8.0.36"


def test_postgres_volume_path():
    pg = engines.get("postgres")
    assert pg.spec("18")["volume_path"] == "/var/lib/postgresql"
    assert pg.spec("16")["volume_path"] == "/var/lib/postgresql/data"


@pytest.mark.parametrize("name", list(engines.ENGINES))
def test_compose_generation(name):
    inst = make(name)
    doc = engines.get(name).compose(inst)
    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    svc = yaml.safe_load(text)["services"]["db"]
    assert svc["container_name"] == "dbon-t"
    assert svc["ports"] == [f"12345:{engines.get(name).port}"]
    assert svc["labels"]["dbon.managed"] == "true"
    assert svc["restart"] == "no"  # must stay a string, not YAML bool
    assert svc["volumes"][0].startswith("data:/")
    assert yaml.safe_load(text)["volumes"]["data"]["labels"]["dbon.instance"] == "t"


def test_oracle_versions():
    inst = make("oracle", "23")
    assert inst.extra["service"] == "FREEPDB1"
    assert "ORACLE_PASSWORD" in engines.get("oracle").environment(inst)
    inst19 = make("oracle", "19")
    assert inst19.extra["service"] == "ORCL"
    assert engines.get("oracle").environment(inst19)["ORACLE_SID"] == "ORCL"


def test_cubrid_probe_passwords():
    inst = make("cubrid")
    eng = engines.get("cubrid")
    assert eng.probe_passwords(inst) == ["", inst.admin_password]
    assert "ALTER USER dba" in eng.bootstrap_sql(inst, "")
    inst.bootstrapped = True
    assert eng.probe_passwords(inst) == [inst.admin_password]


# ---- instance ----------------------------------------------------------------
def test_default_name():
    assert instance.default_name("mysql", "8.4", []) == "mysql84"
    assert instance.default_name("mysql", "8.4", ["mysql84", "mysql84-2"]) == "mysql84-3"


def test_allocate_port():
    busy = {3306, 3308}
    assert instance.allocate_port(3306, {3307}, is_free=lambda p: p not in busy) == 3309


def test_instance_roundtrip():
    inst = make("postgres")
    inst.save()
    loaded = instance.load("t")
    assert loaded == inst
    assert [i.name for i in instance.load_all()] == ["t"]


# ---- dummy data --------------------------------------------------------------
def test_generate_counts_and_fk():
    tables = {t.name: t for t in generate(50, seed=1)}
    assert len(tables["dbon_dept"].rows) == 5
    assert len(tables["dbon_emp"].rows) == 50
    dept_ids = {r[0] for r in tables["dbon_dept"].rows}
    assert all(r[1] in dept_ids for r in tables["dbon_emp"].rows)
    assert generate(10, seed=7)[1].rows == generate(10, seed=7)[1].rows


def test_literals():
    assert Dialect("mssql").literal("가'나") == "N'가''나'"
    assert Dialect("mysql").literal("a\\b") == "'a\\\\b'"
    assert Dialect("oracle").literal(date(2024, 1, 2)) == "DATE '2024-01-02'"
    assert Dialect("cubrid").literal(datetime(2024, 1, 2, 3, 4, 5)) == "DATETIME '2024-01-02 03:04:05'"
    assert Dialect("mysql").literal(datetime(2024, 1, 2, 3, 4, 5)) == "'2024-01-02 03:04:05'"
    assert Dialect("postgres").literal(None) == "NULL"
    assert Dialect("postgres").literal(Decimal("1.50")) == "1.50"


@pytest.mark.parametrize("dialect", DIALECTS)
def test_render_script(dialect):
    sql = render(dialect, 1200, seed=3)
    assert "CREATE TABLE dbon_orders" in sql
    if dialect == "oracle":
        assert "INSERT ALL" in sql and "CASCADE CONSTRAINTS" in sql
    elif dialect == "sybase":
        assert "IF OBJECT_ID('dbon_orders') IS NOT NULL DROP TABLE dbon_orders" in sql
    elif dialect == "altibase":
        assert "EXECUTE IMMEDIATE 'DROP TABLE dbon_orders CASCADE'" in sql and "IF EXISTS" not in sql
    else:
        assert "DROP TABLE IF EXISTS dbon_orders;" in sql
    if dialect == "mssql":
        assert "\nGO\n" in sql
        assert "NVARCHAR" in sql


# ---- sybase ------------------------------------------------------------------
def test_sybase_dialect():
    sql = render("sybase", 450, seed=1)
    assert "UNIVARCHAR(50)" in sql and "NOT NULL" in sql
    assert "emp_memo UNIVARCHAR(200) NULL" in sql  # ASE defaults columns to NOT NULL
    assert "UNION ALL SELECT" in sql and "VALUES" not in sql  # ASE has no multi-row VALUES
    # 450 emp rows in batches of 200 -> 3 batches, each closed by GO
    emp_batches = [b for b in sql.split("\nGO\n") if b.startswith("INSERT INTO dbon_emp")]
    assert len(emp_batches) == 3
    assert Dialect("sybase").literal("가'나") == "'가''나'"


def test_sybase_engine():
    eng = engines.get("ase")
    inst = make("sybase")
    svc = eng.compose(inst)["services"]["db"]
    assert svc["entrypoint"][0] == "bash" and "$$PID" in svc["entrypoint"][2]
    assert svc["volumes"] == ["data:/opt/sybase/data"]
    assert eng.probe_passwords(inst) == ["myPassword", inst.admin_password]
    assert "sp_password 'myPassword'" in eng.bootstrap_sql(inst, "myPassword")
    assert "sp_password" not in eng.bootstrap_sql(inst, inst.admin_password)
    assert eng.wrap_script("select 1") == "select 1\ngo\n"
    assert eng.wrap_script("select 1\nGO\n") == "select 1\nGO\n"
    inst.bootstrapped = True
    assert eng.probe_passwords(inst) == [inst.admin_password]


# ---- db2 ---------------------------------------------------------------------
def test_db2_dialect():
    sql = render("db2", 10, seed=1)
    assert "emp_name VARCHAR(50 CODEUNITS32) NOT NULL" in sql
    assert "gender CHAR(1 CODEUNITS32)" in sql
    assert "created_at TIMESTAMP(0)" in sql
    assert "DROP TABLE IF EXISTS dbon_orders;" in sql
    assert Dialect("db2").literal(date(2024, 1, 2)) == "DATE '2024-01-02'"
    assert Dialect("db2").literal(datetime(2024, 1, 2, 3, 4, 5)) == "TIMESTAMP '2024-01-02 03:04:05'"


def test_db2_engine():
    eng = engines.get("db2")
    inst = make("db2")
    svc = eng.compose(inst)["services"]["db"]
    assert svc["privileged"] is True
    assert svc["volumes"] == ["data:/database"]
    assert svc["environment"]["LICENSE"] == "accept"
    assert svc["environment"]["DB2INST1_PASSWORD"] == inst.admin_password
    assert svc["environment"]["DBNAME"] == "testdb"
    assert eng.jdbc_url(inst) == "jdbc:db2://localhost:12345/testdb"
    assert eng.spec("latest") == {"image": "ibmcom/db2:latest", "volume_path": "/database"}
    assert eng.spec("11.5.8.0")["image"] == "ibmcom/db2:11.5.8.0"
    assert eng.spec("12.1.5.0") == {"image": "icr.io/db2_community/db2:12.1.5.0", "volume_path": "/database"}
    assert make("db2", "12.1.5.0").image == "icr.io/db2_community/db2:12.1.5.0"
    assert eng.default_version == "11.5.8.0"


def test_db2_exec_uses_instance_owner_and_utf8_client():
    eng = engines.get("db2")
    inst = make("db2")
    spec = eng.exec_sql(inst, "/tmp/x.sql", admin=False)
    assert spec.user == "db2inst1"
    assert spec.cmd[-2:] == ["-stf", "/tmp/x.sql"]
    assert spec.env["DB2CODEPAGE"] == "1208"
    assert (spec.env["DBON_U"], spec.env["DBON_P"]) == (inst.user, inst.password)
    admin = eng.exec_sql(inst, "/tmp/x.sql", admin=True, admin_password="other")
    assert (admin.env["DBON_U"], admin.env["DBON_P"]) == ("db2inst1", "other")


def test_db2_accounts():
    eng = engines.get("db2")
    inst = make("db2")
    assert "TO USER dbon" in eng.bootstrap_sql(inst, inst.admin_password)
    os_user = eng.on_ready(inst)[0]  # Db2 authenticates against OS accounts
    assert os_user.user == "0"
    assert os_user.env == {"DBON_U": "dbon", "DBON_P": inst.password}


@pytest.mark.parametrize("field,value", [("database", "toolongdb"), ("user", "db2inst1"), ("user", "DB2FENC1")])
def test_db2_rejects_unusable_names(field, value):
    inst = make("postgres")
    inst.engine, inst.version = "db2", "11.5.8.0"
    setattr(inst, field, value)
    with pytest.raises(engines.EngineError):
        engines.get("db2").prepare(inst)


def test_first_use_notice_shown_once(home, capsys):
    db2 = engines.get("db2")
    cli._notify_first_use(db2)
    out = capsys.readouterr().out
    assert "license" in out and "agree" in out
    assert (home / "notices" / "db2").exists()
    cli._notify_first_use(db2)
    assert capsys.readouterr().out == ""
    cli._notify_first_use(engines.get("mysql"))  # engines without a notice stay silent
    assert capsys.readouterr().out == ""


# ---- altibase -----------------------------------------------------------------
def test_altibase_dialect():
    sql = render("altibase", 450, seed=1)
    assert "emp_name NVARCHAR(50) NOT NULL" in sql
    assert "gender NCHAR(1)" in sql
    assert "created_at DATE" in sql
    # 450 emp rows in batches of 200 (isql rejects much longer statements)
    assert sql.count("INSERT INTO dbon_emp ") == 3
    alti = Dialect("altibase")
    assert alti.literal(date(2024, 1, 2)) == "TO_DATE('2024-01-02', 'YYYY-MM-DD')"
    assert alti.literal(datetime(2024, 1, 2, 3, 4, 5)) == "TO_DATE('2024-01-02 03:04:05', 'YYYY-MM-DD HH24:MI:SS')"
    assert alti.literal("가'나") == "'가''나'"


def test_altibase_engine():
    eng = engines.get("alti")
    inst = make("altibase")
    doc = eng.compose(inst)
    svc = doc["services"]["db"]
    assert svc["entrypoint"][0] == "bash" and "$$DBON_SYS_PASSWORD" in svc["entrypoint"][2]
    assert svc["volumes"] == ["data:/root/altibase_home/dbs", "logs:/root/altibase_home/logs"]
    assert doc["volumes"]["logs"]["labels"]["dbon.managed"] == "true"
    assert "privileged" not in svc
    assert inst.database == "mydb"  # prebuilt in the image
    assert eng.jdbc_url(inst) == "jdbc:Altibase://localhost:12345/mydb"
    assert "NON-COMMERCIAL" in eng.first_use_notice


def test_altibase_accounts():
    eng = engines.get("altibase")
    inst = make("altibase")
    assert eng.probe_passwords(inst) == ["manager", inst.admin_password]
    sql = eng.bootstrap_sql(inst, "manager")
    assert f'CREATE USER dbon IDENTIFIED BY "{inst.password}"' in sql
    assert f'ALTER USER sys IDENTIFIED BY "{inst.admin_password}";' in sql
    assert "ALTER USER sys" not in eng.bootstrap_sql(inst, inst.admin_password)
    inst.bootstrapped = True
    assert eng.probe_passwords(inst) == [inst.admin_password]
    assert eng.wrap_script("SELECT 1 FROM dual;\n") == "SELECT 1 FROM dual;\nquit\n"


def test_altibase_rejects_reserved_user():
    inst = make("postgres")
    inst.engine, inst.version, inst.user = "altibase", "7.3", "SYS"
    with pytest.raises(engines.EngineError):
        engines.get("altibase").prepare(inst)


def test_altibase_error_detection():
    out = "iSQL> SELECT 1;\n[ERR-31031 : Table or view was not found]\n" + "iSQL> more\n" * 100
    assert runner._has_error("altibase", out)
    assert not runner._has_error("altibase", "iSQL> SELECT '[ERR-' FROM dual;\n1 row selected.\n")
    assert runner._failure_excerpt("altibase", out).startswith("[ERR-31031")
    assert not runner._has_error("mysql", out)


def test_extra_env_in_compose():
    inst = make("mssql", "2019")
    inst.extra["env"] = {"MSSQL_COLLATION": "Korean_Wansung_CI_AS"}
    env = engines.get("mssql").compose(inst)["services"]["db"]["environment"]
    assert env["MSSQL_COLLATION"] == "Korean_Wansung_CI_AS"
    assert env["ACCEPT_EULA"] == "Y"  # engine defaults are kept
