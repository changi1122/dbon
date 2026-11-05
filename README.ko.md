# dbon

[English](README.md) | **한국어**

개발/테스트용 DBMS 컨테이너를 Docker Compose로 띄우고, 계정 생성과 더미데이터 적재, 정리까지 한 번에 해주는 CLI입니다.

지원: Oracle(11/19/21/23), PostgreSQL(13-18), MySQL(5.7/8.0/8.4/9), MariaDB(10.6/10.11/11.4/11.8), SQL Server(2019/2022/2025), CUBRID(11.0-11.4), SAP ASE/Sybase(16.0), IBM Db2(11.5.4.0/11.5.5.1/11.5.8.0)

자세한 설계는 [SPEC.md](SPEC.md)를 참고하세요.

## 설치

Windows에서는 Docker Desktop, Linux에서는 Docker Engine과 Docker Compose v2가 필요합니다.

### Windows (PowerShell)

프로젝트 디렉터리에서 가상환경을 만들고 `dbon`을 설치합니다.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
```

#### `dbon` 명령을 어디서나 사용하기 (권장: pipx)

`pipx`를 설치하고 사용자 PATH를 설정한 다음, editable 모드로 프로젝트를 설치합니다.

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install -e C:\project\dbon
```

`C:\project\dbon`은 실제 프로젝트 경로로 바꾸세요. 새 터미널을 열고 다음 명령으로 설치를 확인합니다.

```powershell
dbon engines
```

제거하려면 다음 명령을 실행합니다.

```powershell
py -m pipx uninstall dbon
```

`pyproject.toml`의 의존성을 변경했다면 다음 명령으로 다시 설치합니다.

```powershell
py -m pipx reinstall dbon
```

또는 가상환경의 `Scripts` 디렉터리를 사용자 PATH에 추가할 수 있습니다.

```powershell
[Environment]::SetEnvironmentVariable(
    "Path",
    [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\project\dbon\.venv\Scripts",
    "User"
)
```

예시 경로를 실제 프로젝트 경로로 바꾸세요. PATH 변경 사항을 적용하려면 새 터미널을 열어야 합니다.

### Linux (Bash)

프로젝트 디렉터리에서 가상환경을 만들고 `dbon`을 설치합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

#### `dbon` 명령을 어디서나 사용하기 (권장: pipx)

가능하면 배포판의 패키지 관리자로 `pipx`를 설치합니다. 예를 들어 Ubuntu/Debian에서는 다음과 같이 실행합니다.

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
```

그런 다음 editable 모드로 프로젝트를 설치합니다. `/path/to/dbon`은 로컬 저장소의 실제 경로로 바꾸세요.

```bash
pipx install -e /path/to/dbon
```

새 터미널을 열고 설치를 확인합니다.

```bash
dbon engines
```

제거하려면 다음 명령을 실행합니다.

```bash
pipx uninstall dbon
```

`pyproject.toml`의 의존성을 변경했다면 다음 명령으로 다시 설치합니다.

```bash
pipx reinstall dbon
```

또는 가상환경의 `bin` 디렉터리를 PATH에 추가할 수 있습니다. `~/.bashrc`에 다음 줄을 추가하세요.

```bash
export PATH="/path/to/dbon/.venv/bin:$PATH"
```

`/path/to/dbon`을 실제 프로젝트 경로로 바꾼 다음 셸 설정을 다시 불러옵니다.

```bash
source ~/.bashrc
```

Docker가 설치되어 실행 중이어야 하며, 현재 사용자에게 Docker 데몬에 접근할 권한이 있어야 합니다. Docker 접근 권한을 설정할 때는 사용 중인 Linux 배포판의 Docker 문서를 참고하세요.

## 사용 예

```bash
dbon engines                       # 지원 엔진/버전
dbon up mysql                      # MySQL 8.4 + 계정(dbon/dbon1234) + 더미데이터 100건
dbon up pg:16 --rows 10000 --seed 42
dbon up oracle:19 --name ora-a     # 같은 엔진 여러 개 → 포트 자동 할당(1521, 1522, …)
dbon up mssql:2022 --rows 0        # 더미데이터 없이
dbon up sybase                     # SAP ASE 16.0 (이미지 약 9GB, amd64)
dbon up db2                        # IBM Db2 11.5.8.0 (이미지 약 4GB, privileged 실행)
dbon ls                            # 목록/상태
dbon info mysql84                  # 접속 정보, JDBC URL
dbon shell mysql84 [--admin]       # 컨테이너 안의 mysql/psql/sqlplus/sqlcmd/csql/isql/db2 접속
dbon sql mysql84 ./my.sql          # SQL 파일 실행
dbon seed mysql84 --rows 5000      # 더미데이터 재생성
dbon stop mysql84                  # 중지(데이터 보존)
dbon start mysql84
dbon rm mysql84                    # 컨테이너 + 볼륨 + 작업폴더 삭제
dbon prune                         # dbon이 만든 리소스 전부 삭제
dbon gen oracle --rows 1000 -o dummy.sql   # SQL 파일만 생성
```

### IBM Db2 라이선스

Db2 이미지는 IBM Db2 Community Edition 라이선스를 따르며, dbon이 컨테이너에 `LICENSE=accept`를 설정합니다. dbon으로 Db2를 사용하면 [해당 라이선스](https://hub.docker.com/r/ibmcom/db2)에 동의하는 것입니다. 최초 `dbon up db2` 때 CLI에서 한 번 안내합니다.

Db2의 DB 이름은 최대 8자입니다.

## 계정 설정

`~/.dbon/config.yaml` (첫 실행 시 생성, `dbon config show`)에서 기본 계정/비밀번호를 관리합니다.
우선순위: CLI 옵션 > `engines.<engine>.versions.<ver>` > `engines.<engine>` > `defaults`.

작업 폴더 위치는 환경변수 `DBON_HOME`으로 바꿀 수 있습니다.

## 더미데이터

`dbon_dept`, `dbon_emp`, `dbon_customer`, `dbon_orders` 4개 테이블(FK 포함)에 한글 이름/주소, 날짜, 금액, NULL 값이 섞인 랜덤 데이터를 넣습니다.

## 테스트

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
