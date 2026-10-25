from datetime import date, datetime
from decimal import Decimal

import pytest
import yaml

from dbon import config, engines, instance
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
        engines.parse_target("db2")
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
