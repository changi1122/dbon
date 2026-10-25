# dbon

**English** | [한국어](README.ko.md)

A CLI that uses Docker Compose to launch DBMS containers for development and testing, create database accounts, load dummy data, and clean up resources in one go.

**Supported engines and versions:** Oracle (11/19/21/23), PostgreSQL (13–18), MySQL (5.7/8.0/8.4/9), MariaDB (10.6/10.11/11.4/11.8), SQL Server (2019/2022/2025), CUBRID (11.0–11.4), and SAP ASE/Sybase (16.0).

See [SPEC.md](SPEC.md) for the detailed design specification.

## Installation

`dbon` requires Docker Desktop on Windows, or Docker Engine with Docker Compose v2 on Linux.

### Windows (PowerShell)

Create a virtual environment and install `dbon` from the project directory:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
```

#### Make the `dbon` command available everywhere (recommended: pipx)

Install `pipx`, ensure its executable directory is on your user PATH, and install the project in editable mode:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install -e C:\project\dbon
```

Replace `C:\project\dbon` with the actual path to your local clone. Open a new terminal, then verify the installation:

```powershell
dbon engines
```

To uninstall `dbon`:

```powershell
py -m pipx uninstall dbon
```

If you change dependencies in `pyproject.toml`, reinstall the environment:

```powershell
py -m pipx reinstall dbon
```

Alternatively, add the virtual environment's `Scripts` directory to your user PATH:

```powershell
[Environment]::SetEnvironmentVariable(
    "Path",
    [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\project\dbon\.venv\Scripts",
    "User"
)
```

Replace the example path with your actual project path. Open a new terminal for PATH changes to take effect.

### Linux (Bash)

Create a virtual environment and install `dbon` from the project directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

#### Make the `dbon` command available everywhere (recommended: pipx)

Install `pipx` using your distribution's package manager when available. For example, on Ubuntu/Debian:

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
```

Then install the project in editable mode (replace the example path with the actual path to your local clone):

```bash
pipx install -e /path/to/dbon
```

Open a new terminal and verify the installation:

```bash
dbon engines
```

To uninstall `dbon`:

```bash
pipx uninstall dbon
```

If you change dependencies in `pyproject.toml`, reinstall the environment:

```bash
pipx reinstall dbon
```

Alternatively, add the virtual environment's `bin` directory to your PATH. Add the following line to `~/.bashrc`:

```bash
export PATH="/path/to/dbon/.venv/bin:$PATH"
```

Replace `/path/to/dbon` with your actual project path, then reload the shell configuration:

```bash
source ~/.bashrc
```

Docker must be installed and running, and your user must have permission to access the Docker daemon. Follow your distribution's Docker documentation to configure access.

## Usage examples

```bash
dbon engines                              # List supported engines and versions
dbon up mysql                             # MySQL 8.4 + account (dbon/dbon1234) + 100 dummy rows
dbon up pg:16 --rows 10000 --seed 42
dbon up oracle:19 --name ora-a            # Automatically assign ports for multiple instances (1521, 1522, ...)
dbon up mssql:2022 --rows 0               # Start without dummy data
dbon up sybase                            # SAP ASE 16.0 (image is approximately 9 GB; amd64)
dbon ls                                   # List instances and their status
dbon info mysql84                         # Show connection details and JDBC URL
dbon shell mysql84 [--admin]              # Open mysql/psql/sqlplus/sqlcmd/csql/isql inside the container
dbon sql mysql84 ./my.sql                 # Execute an SQL file
dbon seed mysql84 --rows 5000             # Regenerate dummy data
dbon stop mysql84                         # Stop the container while preserving data
dbon start mysql84
dbon rm mysql84                           # Remove the container, volume, and working directory
dbon prune                                # Remove all resources created by dbon
dbon gen oracle --rows 1000 -o dummy.sql  # Generate an SQL file only
```

## Account configuration

Default usernames and passwords are managed in `~/.dbon/config.yaml`, which is created on first run. View the configuration with `dbon config show`.

Configuration precedence:

`CLI options > engines.<engine>.versions.<ver> > engines.<engine> > defaults`

Set the `DBON_HOME` environment variable to change the location of the working directory.

## Dummy data

Random data is inserted into four tables: `dbon_dept`, `dbon_emp`, `dbon_customer`, and `dbon_orders`. The tables include foreign-key relationships and data such as Korean names and addresses, dates, monetary amounts, and `NULL` values.

## Tests

Windows (PowerShell):

```powershell
.venv\\Scripts\\python -m pip install -e ".[dev]"
.venv\\Scripts\\python -m pytest
```

Linux (Bash):

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
```
