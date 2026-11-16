# dbon

**English** | [한국어](README.ko.md)

A CLI that uses Docker Compose to launch DBMS containers for development and testing, create database accounts, load dummy data, and clean up resources in one go.

**Supported engines and versions:** Oracle (11/19/21/23), PostgreSQL (13–18), MySQL (5.7/8.0/8.4/9), MariaDB (10.6/10.11/11.4/11.8), SQL Server (2019/2022/2025), CUBRID (11.0–11.4), SAP ASE/Sybase (16.0), IBM Db2 (11.5.4.0/11.5.5.1/11.5.8.0/12.1.5.0), Altibase A+ Edition (7.3; non-commercial use only), Firebird (3/4/5), and SAP IQ/Sybase IQ (16.1; evaluation edition).

See [SPEC.md](SPEC.md) for the detailed design specification.

## Installation

`dbon` requires Docker Desktop on Windows, or Docker Engine with Docker Compose v2 on Linux.

### Windows (PowerShell)

Clone the repository, then create a virtual environment and install `dbon` from the project directory:

```powershell
git clone https://github.com/changi1122/dbon.git
cd dbon
python -m venv .venv
.venv\Scripts\python -m pip install -e .
```

#### Make the `dbon` command available everywhere (recommended: pipx)

From the project directory, install `pipx`, ensure its executable directory is on your user PATH, and install the project in editable mode:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install --force -e .
```

Open a new terminal, then verify the installation:

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

Alternatively, from the project directory, add the virtual environment's `Scripts` directory to your user PATH:

```powershell
[Environment]::SetEnvironmentVariable(
    "Path",
    [Environment]::GetEnvironmentVariable("Path", "User") + ";$(Resolve-Path .venv\Scripts)",
    "User"
)
```

Open a new terminal for PATH changes to take effect.

### Linux (Bash)

Clone the repository, then create a virtual environment and install `dbon` from the project directory:

```bash
git clone https://github.com/changi1122/dbon.git
cd dbon
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

Then install the project in editable mode from the project directory:

```bash
pipx install --force -e .
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

Alternatively, from the project directory, add the virtual environment's `bin` directory to your PATH in `~/.bashrc` and reload the shell configuration:

```bash
echo "export PATH=\"$PWD/.venv/bin:\$PATH\"" >> ~/.bashrc
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
dbon up db2                               # IBM Db2 11.5.8.0 (image is approximately 4 GB; runs privileged)
dbon up db2:12.1.5.0                      # IBM Db2 12.1.5.0 (image is approximately 7 GB; runs privileged)
dbon up altibase                          # Altibase A+ Edition 7.3 (image is approximately 6 GB; amd64; non-commercial use only)
dbon up firebird                          # Firebird 5
dbon up sybaseiq                          # SAP IQ (Sybase IQ) 16.1 (community image, approximately 7.5 GB; amd64; evaluation license)
dbon ls                                   # List instances and their status
dbon info mysql84                         # Show connection details and JDBC URL
dbon shell mysql84 [--admin]              # Open mysql/psql/sqlplus/sqlcmd/csql/isql/db2/dbisql inside the container
dbon sql mysql84 ./my.sql                 # Execute an SQL file
dbon seed mysql84 --rows 5000             # Regenerate dummy data
dbon stop mysql84                         # Stop the container while preserving data
dbon start mysql84
dbon rm mysql84                           # Remove the container, volume, and working directory
dbon prune                                # Remove all resources created by dbon
dbon gen oracle --rows 1000 -o dummy.sql  # Generate an SQL file only
```

### IBM Db2 license

The Db2 image runs under the IBM Db2 Community Edition license, and dbon sets `LICENSE=accept` for the container. By using Db2 through dbon you agree to that license, which is included in the image under `/licenses`. The CLI reminds you of this on your first `dbon up db2`.

Db2 database names are limited to 8 characters.

### Altibase license

Altibase A+ Edition is licensed for **non-commercial use only**. By using it through dbon you agree to its EULA, which is included in the image at `/root/altibase_home/conf/Altibase-A+Edition-EULA.txt`. The CLI reminds you of this on your first `dbon up altibase`.

The image ships a prebuilt UTF8 database named `mydb`, so `--database` has no effect on Altibase. Passwords are not case-sensitive.

### SAP IQ (Sybase IQ)

SAP does not publish an IQ image, so dbon uses the community image `baeghaeun/sybase_iq:16.1`, which contains an evaluation copy of SAP IQ 16.1. `sybase` still means SAP ASE; use `sybaseiq` (aliases `iq`, `sapiq`, `sybase-iq`, `sap-iq`) for IQ.

The database bundled in the image has an expired evaluation license, so on first start dbon creates a new UTF-8 database named after `--database`, which starts a new evaluation period. Once that period ends, the server no longer starts (`No SYSAM License Available` in `dbon logs`); recreate the instance with `dbon rm` and `dbon up` to continue, which deletes its data. The CLI reminds you of this on your first `dbon up sybaseiq`.

IQ dbspaces do not grow on their own: the main store is 500 MB and the temporary store 200 MB. Set larger sizes (in MB) when creating the instance, for example `dbon up sybaseiq --env DBON_IQ_SIZE=2000 --env DBON_IQ_TEMP_SIZE=500`. Passwords cannot contain `;`.

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
