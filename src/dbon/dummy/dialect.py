"""Render dummy tables as DBMS-specific SQL scripts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

from dbon.dummy.data import Column, Table, generate

DIALECTS = ("oracle", "postgres", "mysql", "mariadb", "mssql", "cubrid", "sybase", "db2", "altibase", "firebird", "sybaseiq", "hana")

_TYPES = {
    "oracle": {"int": "NUMBER(10)", "varchar": "VARCHAR2({0} CHAR)", "char": "CHAR({0} CHAR)",
               "decimal": "NUMBER({0},{1})", "date": "DATE", "timestamp": "TIMESTAMP"},
    "postgres": {"int": "INTEGER", "varchar": "VARCHAR({0})", "char": "CHAR({0})",
                 "decimal": "NUMERIC({0},{1})", "date": "DATE", "timestamp": "TIMESTAMP"},
    "mysql": {"int": "INT", "varchar": "VARCHAR({0})", "char": "CHAR({0})",
              "decimal": "DECIMAL({0},{1})", "date": "DATE", "timestamp": "DATETIME"},
    "mssql": {"int": "INT", "varchar": "NVARCHAR({0})", "char": "NCHAR({0})",
              "decimal": "DECIMAL({0},{1})", "date": "DATE", "timestamp": "DATETIME2(0)"},
    "cubrid": {"int": "INTEGER", "varchar": "VARCHAR({0})", "char": "CHAR({0})",
               "decimal": "NUMERIC({0},{1})", "date": "DATE", "timestamp": "DATETIME"},
    # ASE default charset in the datagrip image is iso_1: Korean only fits in Unicode types
    "sybase": {"int": "INT", "varchar": "UNIVARCHAR({0})", "char": "UNICHAR({0})",
               "decimal": "DECIMAL({0},{1})", "date": "DATE", "timestamp": "DATETIME"},
    # VARCHAR(n) counts bytes in a UTF-8 database: CODEUNITS32 counts characters, like oracle's CHAR semantics
    "db2": {"int": "INTEGER", "varchar": "VARCHAR({0} CODEUNITS32)", "char": "CHAR({0} CODEUNITS32)",
            "decimal": "DECIMAL({0},{1})", "date": "DATE", "timestamp": "TIMESTAMP(0)"},
    # VARCHAR(n) counts bytes; DATE carries the time as well
    "firebird": {"int": "INTEGER", "varchar": "VARCHAR({0})", "char": "CHAR({0})",
                 "decimal": "DECIMAL({0},{1})", "date": "DATE", "timestamp": "TIMESTAMP"},
    "altibase": {"int": "INTEGER", "varchar": "NVARCHAR({0})", "char": "NCHAR({0})",
                 "decimal": "NUMERIC({0},{1})", "date": "DATE", "timestamp": "DATE"},
    # the IQ main store has no NCHAR/NVARCHAR or character-length semantics: VARCHAR(n) counts UTF-8 bytes
    "sybaseiq": {"int": "INTEGER", "varchar": "VARCHAR({0})", "char": "CHAR({0})",
                 "decimal": "DECIMAL({0},{1})", "date": "DATE", "timestamp": "TIMESTAMP"},
    "hana": {"int": "INTEGER", "varchar": "NVARCHAR({0})", "char": "NCHAR({0})",
             "decimal": "DECIMAL({0},{1})", "date": "DATE", "timestamp": "TIMESTAMP"},
}
_TYPES["mariadb"] = _TYPES["mysql"]

# altibase isql rejects ~110KB statements; firebird allows at most 255 contexts (UNION ALL branches) in a statement
BATCH = {"oracle": 200, "mssql": 500, "sybase": 200, "altibase": 200, "firebird": 200, "hana": 500}
DEFAULT_BATCH = 500


class Dialect:
    def __init__(self, name: str):
        if name not in DIALECTS:
            raise ValueError(f"unknown dialect: {name}")
        self.name = name
        self.batch = BATCH.get(name, DEFAULT_BATCH)

    # ---- literals -----------------------------------------------------------
    def literal(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, Decimal)):
            return str(value)
        if isinstance(value, datetime):
            s = value.strftime("%Y-%m-%d %H:%M:%S")
            if self.name == "altibase":
                return f"TO_DATE('{s}', 'YYYY-MM-DD HH24:MI:SS')"
            return {"oracle": f"TIMESTAMP '{s}'", "postgres": f"TIMESTAMP '{s}'", "cubrid": f"DATETIME '{s}'",
                    "db2": f"TIMESTAMP '{s}'", "firebird": f"TIMESTAMP '{s}'", "hana": f"TIMESTAMP '{s}'"}.get(self.name, f"'{s}'")
        if isinstance(value, date):
            s = value.isoformat()
            if self.name == "altibase":
                return f"TO_DATE('{s}', 'YYYY-MM-DD')"
            return f"DATE '{s}'" if self.name in ("oracle", "postgres", "cubrid", "db2", "firebird", "hana") else f"'{s}'"
        s = str(value).replace("'", "''")
        if self.name in ("mysql", "mariadb"):
            s = s.replace("\\", "\\\\")
        return f"N'{s}'" if self.name == "mssql" else f"'{s}'"

    # ---- DDL ----------------------------------------------------------------
    def column_type(self, col: Column) -> str:
        size = col.size
        if self.name == "sybaseiq" and col.type == "varchar":
            size = (size[0] * 3,)  # room for 3-byte UTF-8 characters such as Korean
        return _TYPES[self.name][col.type].format(*size)

    def create_table(self, table: Table) -> str:
        lines = []
        pks = [c.name for c in table.columns if c.pk]
        for c in table.columns:
            parts = [f"  {c.name} {self.column_type(c)}"]
            if not c.nullable:
                parts.append("NOT NULL")
            elif self.name == "sybase":
                parts.append("NULL")  # ASE columns default to NOT NULL
            if c.pk and len(pks) == 1:
                parts.append("PRIMARY KEY")
            lines.append(" ".join(parts))
        if len(pks) > 1:
            lines.append(f"  PRIMARY KEY ({', '.join(pks)})")
        for c in table.columns:
            if c.ref:
                lines.append(f"  FOREIGN KEY ({c.name}) REFERENCES {c.ref}")
        suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" if self.name in ("mysql", "mariadb") else ""
        end = "" if self.name == "sybase" else ";"  # ASE rejects a trailing semicolon here
        return f"CREATE TABLE {table.name} (\n" + ",\n".join(lines) + f"\n){suffix}{end}"

    def drop_table(self, name: str) -> str:
        if self.name == "oracle":
            return (
                "BEGIN\n"
                f"  EXECUTE IMMEDIATE 'DROP TABLE {name} CASCADE CONSTRAINTS PURGE';\n"
                "EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF;\n"
                "END;\n/"
            )
        if self.name == "sybase":
            return f"IF OBJECT_ID('{name}') IS NOT NULL DROP TABLE {name}"
        if self.name == "altibase":  # no IF EXISTS; a real failure still surfaces at the CREATE TABLE that follows
            return f"BEGIN\n  EXECUTE IMMEDIATE 'DROP TABLE {name} CASCADE';\nEXCEPTION WHEN OTHERS THEN NULL;\nEND;\n/"
        if self.name == "firebird":  # no IF EXISTS before 6.0; the COMMIT lets the table be re-created
            return (
                "SET TERM ^ ;\n"
                f"EXECUTE BLOCK AS BEGIN\n  IF (EXISTS(SELECT 1 FROM rdb$relations WHERE rdb$relation_name = UPPER('{name}')))"
                f" THEN EXECUTE STATEMENT 'DROP TABLE {name}';\nEND^\n"
                "SET TERM ; ^\nCOMMIT;"
            )
        if self.name == "hana":  # no IF EXISTS in HANA 2.0; 259 = table not found (static DDL: EXEC would warn)
            return (
                "DO BEGIN\n  DECLARE EXIT HANDLER FOR SQL_ERROR_CODE 259 BEGIN END;\n"
                f"  DROP TABLE {name} CASCADE;\nEND;"
            )
        return f"DROP TABLE IF EXISTS {name};"

    # ---- DML ----------------------------------------------------------------
    def inserts(self, table: Table) -> Iterator[str]:
        cols = ", ".join(c.name for c in table.columns)
        for i in range(0, len(table.rows), self.batch):
            chunk = table.rows[i:i + self.batch]
            values = ["(" + ", ".join(self.literal(v) for v in row) + ")" for row in chunk]
            if self.name == "sybase":  # no multi-row VALUES in ASE; UNION ALL is ~100x faster than row-by-row
                selects = ["SELECT " + ", ".join(self.literal(v) for v in row) for row in chunk]
                yield f"INSERT INTO {table.name} ({cols})\n" + "\nUNION ALL ".join(selects)
            elif self.name in ("firebird", "hana"):  # no multi-row VALUES; UNION ALL is much faster than row-by-row
                src = " FROM rdb$database" if self.name == "firebird" else " FROM DUMMY"
                selects = ["SELECT " + ", ".join(self.literal(v) for v in row) + src for row in chunk]
                yield f"INSERT INTO {table.name} ({cols})\n" + "\nUNION ALL ".join(selects) + ";"
            elif self.name == "oracle":
                body = "\n".join(f"  INTO {table.name} ({cols}) VALUES {v}" for v in values)
                yield f"INSERT ALL\n{body}\nSELECT 1 FROM dual;"
            else:
                yield f"INSERT INTO {table.name} ({cols}) VALUES\n" + ",\n".join(values) + ";"

    # ---- script -------------------------------------------------------------
    def script(self, tables: list[Table]) -> str:
        go = self.name in ("mssql", "sybase")
        out: list[str] = [f"-- dbon dummy data ({self.name})"]

        def emit(stmt: str) -> None:
            out.append(stmt)
            if go:
                out.append("GO")

        for t in reversed(tables):  # children first
            emit(self.drop_table(t.name))
        for t in tables:
            emit(self.create_table(t))
        for t in tables:
            for stmt in self.inserts(t):
                emit(stmt)
        return "\n".join(out) + "\n"


def render(dialect: str, rows: int, seed: int | None = None) -> str:
    return Dialect(dialect).script(generate(rows, seed))
