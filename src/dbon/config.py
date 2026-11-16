"""Global configuration (~/.dbon/config.yaml) and credential resolution."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_YAML = """\
# dbon config file
# value resolution priority: CLI 옵션 > engines.<engine>.versions.<ver> > engines.<engine> > defaults
defaults:
  user: dbon              # app user (has dummy data)
  password: dbon!
  admin_password: dbon0000!
  database: testdb
  rows: 100               # dummy data default row count (no dummy if 0)
  timezone: Asia/Seoul
  restart: "no"           # compose restart policy (no / unless-stopped / always)
  timeout: 300            # ready timeout(second)

engines:
  oracle:
    admin_password: DBon0000!
    mem_limit: 4g
    timeout: 1800
  mssql:
    admin_password: DBon0000!
    timeout: 600
  cubrid:
    timeout: 600
  db2:
    timeout: 900
  hana:                   # SAP HANA password rules; the first start installs HANA (~10 min)
    password: dbon1234!
    admin_password: DBon0000!
    timeout: 1800
"""

BUILTIN_DEFAULTS: dict[str, Any] = {
    "user": "dbon",
    "password": "dbon!",
    "admin_password": "DBon0000!",
    "database": "testdb",
    "rows": 100,
    "timezone": "Asia/Seoul",
    "restart": "no",
    "timeout": 300,
    "mem_limit": None,
}

SETTING_KEYS = tuple(BUILTIN_DEFAULTS)

IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
BAD_PASSWORD_CHARS = set("'\"\\` \t\r\n")

class ConfigError(Exception):
    pass

def dbon_home() -> Path:
    env = os.environ.get("DBON_HOME")
    return Path(env).expanduser() if env else Path.home() / ".dbon"

def config_path() -> Path:
    return dbon_home() / "config.yaml"

def init_config(force: bool = False) -> Path:
    path = config_path()
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
    return path

def load_config() -> dict[str, Any]:
    path = init_config()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} parsing failed: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} root should be a mapping.")
    return data

def resolve_settings(
    config: dict[str, Any],
    engine: str,
    version: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge settings: builtin < defaults < engines.<engine> < engines.<engine>.versions.<ver> < overrides."""
    result = dict(BUILTIN_DEFAULTS)
    layers: list[dict[str, Any]] = [config.get("defaults") or {}]
    eng_cfg = (config.get("engines") or {}).get(engine) or {}
    layers.append(eng_cfg)
    versions = eng_cfg.get("versions") or {}
    layers.append(versions.get(version) or versions.get(str(version)) or {})
    layers.append({k: v for k, v in (overrides or {}).items() if v is not None})
    for layer in layers:
        for key in SETTING_KEYS:
            if key in layer:
                result[key] = layer[key]
    for key in ("user", "password", "admin_password", "database", "timezone", "restart"):
        if result[key] is not None:
            result[key] = str(result[key])
    result["rows"] = int(result["rows"])
    result["timeout"] = int(result["timeout"])
    validate_settings(result)
    return result


def validate_settings(s: dict[str, Any]) -> None:
    for key in ("user", "database"):
        if not IDENT_RE.match(s[key]):
            raise ConfigError(
                f"{key} '{s[key]}' must start with a letter and contain only letters, digits, and underscores"
            )
    for key in ("password", "admin_password"):
        value = s[key]
        if not value:
            raise ConfigError(f"{key} must not be empty")
        bad = BAD_PASSWORD_CHARS & set(value)
        if bad:
            raise ConfigError(
                f"{key} contains unsupported characters: {''.join(sorted(bad))!r}"
            )
    if s["rows"] < 0:
        raise ConfigError("rows must be greater than or equal to 0")
