from __future__ import annotations

from dbon.engines.base import Engine, EngineError, ExecSpec
from dbon.engines.cubrid import Cubrid
from dbon.engines.db2 import Db2
from dbon.engines.mssql import MSSQL
from dbon.engines.mysql import MariaDB, MySQL
from dbon.engines.oracle import Oracle
from dbon.engines.postgres import Postgres
from dbon.engines.sybase import Sybase

ENGINES: dict[str, Engine] = {e.name: e for e in (Oracle(), Postgres(), MySQL(), MariaDB(), MSSQL(), Cubrid(), Sybase(), Db2())}

_ALIASES = {alias: e for e in ENGINES.values() for alias in (e.name, *e.aliases)}


def get(name: str) -> Engine:
    engine = _ALIASES.get(name.lower())
    if not engine:
        raise EngineError(
            f"Unsupported engine: {name} (supported: {', '.join(ENGINES)})"
        )
    return engine

def parse_target(target: str) -> tuple[Engine, str]:
    """'mysql:8.0' -> (MySQL, '8.0'); 'pg' -> (Postgres, default version)."""
    name, _, version = target.partition(":")
    engine = get(name)
    return engine, (version or engine.default_version)


__all__ = ["ENGINES", "Engine", "EngineError", "ExecSpec", "get", "parse_target"]
