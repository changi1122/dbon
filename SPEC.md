# dbon — 개발용 DBMS 컨테이너 관리 CLI

## 1. 목적

DBMS 종류/버전별로 Docker Compose 기반 컨테이너를 한 줄 명령으로 띄우고,
계정·비밀번호를 한 곳에서 관리하며, 랜덤 더미데이터를 자동으로 적재하고,
사용이 끝나면 컨테이너·볼륨·생성 파일을 깨끗이 정리한다.

## 2. 지원 DBMS / 버전

| 엔진 (별칭) | 버전 (기본값 **굵게**) | 이미지 | 컨테이너 포트 | 관리자 계정 |
|---|---|---|---|---|
| `oracle` (`ora`) | 11, **19**, 21, 23 | 11: `gvenzl/oracle-xe:11`, 19: `doctorkirk/oracle-19c:19.3`, 21: `gvenzl/oracle-xe:21-slim`, 23: `gvenzl/oracle-free:23-slim` | 1521 | `system` |
| `postgres` (`pg`, `postgresql`) | 13, 14, 15, 16, 17, **18** | `postgres:<ver>` | 5432 | `postgres` |
| `mysql` | 5.7, 8.0, **8.4**, 9 | `mysql:<ver>` | 3306 | `root` |
| `mariadb` (`maria`) | 10.6, 10.11, **11.4**, 11.8 | `mariadb:<ver>` | 3306 | `root` |
| `mssql` (`ms-sql`, `sqlserver`) | 2019, **2022**, 2025 | `mcr.microsoft.com/mssql/server:<ver>-latest` | 1433 | `sa` |
| `cubrid` | 11.0, 11.2, 11.3, **11.4** | `cubrid/cubrid:<ver>` | 33000 (broker) | `dba` |
| `sybase` (`ase`, `sybase-ase`) | **16.0** | `datagrip/sybase:16.0` (ASE 16.0 SP02 Developer Edition, amd64, 약 9GB) | 5000 | `sa` |

- 표에 없는 버전도 `engine:<tag>` 로 지정하면 `<기본 이미지>:<tag>` 로 시도한다 (oracle 제외). `--image` 로 이미지를 직접 지정할 수도 있다.
- 버전별 차이(볼륨 경로, PDB 서비스명, sqlcmd 경로 등)는 엔진 모듈에서 흡수한다.
  - postgres 18+ 데이터 경로는 `/var/lib/postgresql`, 그 이하는 `/var/lib/postgresql/data`
  - sybase: 이미지의 `/entrypoint.sh` 는 기동할 때마다 sa=`myPassword` 로 로그인/DB 생성을 시도하고 종료 처리가 없어,
    compose `entrypoint` 를 dbon 래퍼로 교체한다 (ASE 백그라운드 기동 + `docker stop` 시 `shutdown` 으로 정상 종료). 서버명 `MYSYBASE`.
  - cubrid 데이터 경로는 이미지의 `CUBRID_DATABASES` 환경변수를 조회해 결정 (11.0=`/var/lib/cubrid`, 11.4=`/home/cubrid/CUBRID/databases`)
  - oracle 서비스명: 11=`XE`, 19=`ORCL`(non-CDB), 21=`XEPDB1`, 23=`FREEPDB1`
  - mssql sqlcmd: `/opt/mssql-tools18/bin/sqlcmd -C` 우선, 없으면 `/opt/mssql-tools/bin/sqlcmd`

## 3. 핵심 개념

- **인스턴스**: 이름으로 식별되는 DB 컨테이너 1개. 같은 엔진/버전을 여러 개 동시에 띄울 수 있다.
  - 기본 이름: `<engine><버전에서 점 제거>` (예: `mysql84`, `oracle19`), 중복이면 `-2`, `-3` … 접미사
  - Compose 프로젝트명/컨테이너명: `dbon-<name>`, 볼륨: `dbon-<name>_data`
  - 모든 컨테이너/볼륨에 `dbon.managed=true`, `dbon.instance=<name>` 라벨 부여 → 정리 시 dbon이 만든 리소스만 건드림
- **작업 폴더**: `~/.dbon` (환경변수 `DBON_HOME` 으로 변경 가능)
  ```
  ~/.dbon/
    config.yaml                    # 계정/비밀번호 등 통합 설정
    instances/<name>/
      instance.json                # 엔진, 버전, 포트, 계정, 상태 플래그
      docker-compose.yml           # 생성된 compose 파일
      seed.sql                     # 마지막으로 적재한 더미데이터 SQL
  ```
- **포트 자동 할당**: 엔진 기본 포트부터 1씩 증가하며 (a) 다른 dbon 인스턴스가 예약한 포트, (b) 호스트에서 이미 사용 중인 포트를 피한다. `--port` 로 고정 가능.

## 4. 계정/비밀번호 통합 관리

`~/.dbon/config.yaml` (없으면 첫 실행 시 기본값으로 생성)

```yaml
defaults:
  user: dbon              # 앱 계정 (더미데이터 소유자)
  password: dbon!
  admin_password: DBon0000!
  database: testdb
  rows: 100               # 더미데이터 기본 행 수
  restart: "no"           # compose restart 정책
engines:
  oracle:
    admin_password: DBon0000!
    mem_limit: 4g
    timeout: 1800         # 준비 대기 시간(초)
  mssql:
    admin_password: DBon0000!   # SA 비밀번호 복잡도 정책 충족 필요
    versions:
      "2019":
        mem_limit: 2g
```

- 값 결정 우선순위: **CLI 옵션 > engines.<engine>.versions.<ver> > engines.<engine> > defaults > 내장 기본값**
- 결정된 값은 `instance.json` 에 고정 저장되며, 이후 설정 파일을 바꿔도 기존 인스턴스에는 영향 없음.
- 관리자 계정명은 엔진별로 고정 (위 표). 앱 계정은 생성 후 부트스트랩 단계에서 dbon이 직접 만든다.
- 사용자명/DB명은 `^[A-Za-z][A-Za-z0-9_]*$`, 비밀번호는 `' " \ `` 와 공백 금지 (엔진별 SQL/셸 이스케이프를 단순화하기 위함).
- 로컬 개발용 도구이므로 비밀번호는 평문 저장한다.

## 5. 기동 흐름 (`dbon up`)

1. 엔진/버전 해석 → 인스턴스 이름·포트·계정 결정
2. `instances/<name>/docker-compose.yml`, `instance.json` 생성
3. `docker compose up -d` (이미지 자동 pull)
4. **준비 대기**: 관리자 계정으로 `SELECT 1` 이 성공할 때까지 폴링 (컨테이너 healthcheck가 있으면 healthy도 확인). 초기화 중의 임시 서버를 오판하지 않도록 TCP(127.0.0.1)로 접속한다.
5. **부트스트랩** (최초 1회, 관리자 계정):
   - oracle: PDB에 앱 사용자 생성 + `CONNECT, RESOURCE, CREATE VIEW…` 권한, USERS 테이블스페이스 quota
   - postgres: 앱 role 생성 + 앱 role 소유의 DB 생성
   - mysql/mariadb: DB 생성, `'user'@'%'` 생성 및 해당 DB 전체 권한
   - mssql: DB 생성, LOGIN(CHECK_POLICY=OFF) + DB USER 생성, `db_owner` 부여
   - sybase: master 디바이스를 200MB 늘려 DB 생성(옵션: trunc log on chkpt, ddl in tran, allow nulls by default 등),
     login(default database 지정) + `sp_adduser` + create table/view/procedure 등 권한, sa 비밀번호를 `myPassword` 에서 변경
   - cubrid: DB는 컨테이너 환경변수(`CUBRID_DB`)로 생성됨. 공식 이미지가 dba 비밀번호를 설정하지 않으므로 dba 비밀번호 설정 + 앱 사용자 생성 (별도 이미지 빌드 불필요)
6. **더미데이터 적재** (`--rows 0` 이면 생략): 앱 계정으로 실행
7. 접속 정보(호스트/포트/계정/JDBC URL) 출력

SQL 실행 방식: 파이썬이 엔진 방언 SQL 파일을 생성 → `docker cp` 로 컨테이너에 복사 → 컨테이너 내 CLI로 실행
(`sqlplus`, `psql`, `mysql`, `mariadb`, `sqlcmd`, `csql`). 호스트에 DB 드라이버/클라이언트 설치 불필요.

## 6. 더미데이터

`--rows N`, `--seed S`(재현 가능한 난수) 지정. 테이블은 `dbon_` 접두사, 재적재 시 drop 후 재생성.

| 테이블 | 행 수 | 주요 컬럼 |
|---|---|---|
| `dbon_dept` | max(5, N/20) | dept_id PK, dept_name, location, created_at |
| `dbon_emp` | N | emp_id PK, dept_id FK, emp_name(한글), email, phone, gender CHAR(1), birth_date, hire_date, salary DECIMAL(12,2), is_active CHAR(1), memo(NULL 포함), created_at |
| `dbon_customer` | N | cust_id PK, cust_name, email, phone, address(한글 주소), grade, reg_date |
| `dbon_orders` | N | order_id PK, cust_id FK, emp_id FK, order_date, amount, status |

- 타입 매핑: oracle `NUMBER/VARCHAR2(n CHAR)/DATE/TIMESTAMP`, mssql `NVARCHAR/DATETIME2` + `N'..'` 리터럴, mysql/mariadb `DATETIME`, cubrid `DATETIME`, sybase `UNIVARCHAR/UNICHAR/DATETIME` 등
- 다건 INSERT: oracle `INSERT ALL … SELECT 1 FROM dual`, mssql 1000건 단위 + `GO`, sybase `INSERT … SELECT … UNION ALL` 200건 단위 + `go`, 그 외 multi-row `VALUES`
- sybase 는 `DROP TABLE IF EXISTS`·문장 끝 `;` 미지원, 컬럼 기본값이 NOT NULL 이므로 nullable 컬럼에 `NULL` 을 명시
- 문자셋: oracle AL32UTF8, mysql/mariadb utf8mb4, cubrid `en_US.utf8`, mssql NVARCHAR, sybase 서버 문자셋이 iso_1 이라 UNICODE 타입 + `isql -J utf8`
- 외부 라이브러리(Faker) 없이 내장 한글 이름/주소 생성기 사용

## 7. CLI 명령

```
dbon engines                         # 지원 엔진/버전 목록
dbon up ENGINE[:VERSION] [옵션]      # 생성+기동+부트스트랩+더미데이터
     --name NAME --port PORT --image IMAGE
     --user U --password P --admin-password P --database D
     --rows N --seed S --timeout SEC --no-wait
dbon ls                              # 인스턴스 목록 (상태, 포트)
dbon info NAME                       # 접속 정보 (계정/비밀번호/JDBC URL)
dbon start NAME / stop NAME / restart NAME
dbon logs NAME [-f] [--tail N]
dbon seed NAME [--rows N] [--seed S] # 더미데이터 재생성
dbon sql NAME FILE [--admin]         # SQL 파일 실행
dbon shell NAME [--admin]            # 컨테이너 내 대화형 CLI 접속
dbon rm NAME... [-y] [--keep-volume] # 컨테이너+볼륨+네트워크+작업폴더 삭제
dbon prune [-y]                      # dbon 관리 리소스 전체 정리 (라벨 기준 고아 볼륨 포함)
dbon gen ENGINE --rows N [-o FILE]   # 더미데이터 SQL만 생성 (도커 불필요)
dbon config path|show|init
```

정리 정책: `stop` 은 데이터 보존, `rm` 은 볼륨까지 삭제(확인 프롬프트, `-y` 로 생략), `prune` 은 dbon 라벨이 붙은 모든 리소스 삭제.
dbon 라벨이 없는 기존 컨테이너/볼륨은 절대 건드리지 않는다.

## 8. 구현 구조

```
pyproject.toml                # Python >= 3.10, 의존성: click, PyYAML / 콘솔 스크립트 `dbon`
src/dbon/
  cli.py                      # click 명령 정의
  config.py                   # config.yaml 로드/병합/검증
  instance.py                 # Instance 모델, instance.json 저장/조회, 이름·포트 할당
  docker.py                   # docker / docker compose subprocess 래퍼
  runner.py                   # SQL 파일 복사·실행, 준비 대기, 부트스트랩
  engines/
    base.py                   # Engine 추상 클래스 (이미지, compose 서비스, 실행 명령, 부트스트랩 SQL, JDBC)
    oracle.py postgres.py mysql.py mariadb.py mssql.py cubrid.py sybase.py
  dummy/
    data.py                   # 랜덤 행 생성 (한글 이름/주소 등)
    dialect.py                # 엔진별 DDL/INSERT 렌더링
tests/                        # pytest: compose 생성, 방언 SQL, 설정 병합, 포트 할당
```

## 9. 비범위 (추후 고려)

- 원격 Docker 호스트, Kubernetes
- 사용자 정의 스키마 기반 데이터 생성 (현재는 고정 샘플 스키마 + `dbon sql` 로 임의 SQL 실행)
- SSL 강제, EUC-KR 등 비 UTF-8 문자셋 프리셋
- sybase 15.7(`datagrip/sybase:15.7`), Sybase IQ
- altibase, db2 등 추가 엔진 (엔진 모듈 추가로 확장 가능한 구조)
