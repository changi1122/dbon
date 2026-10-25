"""Random dummy rows for a fixed sample schema (no external faker dependency)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # int | varchar | char | decimal | date | timestamp
    size: tuple[int, ...] = ()
    pk: bool = False
    nullable: bool = True
    ref: str | None = None  # "table(column)"


@dataclass
class Table:
    name: str
    columns: list[Column]
    rows: list[tuple[Any, ...]]


def _schema() -> dict[str, list[Column]]:
    C = Column
    return {
        "dbon_dept": [
            C("dept_id", "int", pk=True, nullable=False),
            C("dept_name", "varchar", (50,), nullable=False),
            C("dept_loc", "varchar", (50,)),
            C("created_at", "timestamp"),
        ],
        "dbon_emp": [
            C("emp_id", "int", pk=True, nullable=False),
            C("dept_id", "int", ref="dbon_dept(dept_id)"),
            C("emp_name", "varchar", (50,), nullable=False),
            C("email", "varchar", (100,)),
            C("phone", "varchar", (20,)),
            C("gender", "char", (1,)),
            C("birth_date", "date"),
            C("hire_date", "date"),
            C("salary", "decimal", (12, 2)),
            C("is_active", "char", (1,)),
            C("emp_memo", "varchar", (200,)),
            C("created_at", "timestamp"),
        ],
        "dbon_customer": [
            C("cust_id", "int", pk=True, nullable=False),
            C("cust_name", "varchar", (50,), nullable=False),
            C("email", "varchar", (100,)),
            C("phone", "varchar", (20,)),
            C("address", "varchar", (200,)),
            C("cust_grade", "varchar", (10,)),
            C("reg_date", "date"),
        ],
        "dbon_orders": [
            C("order_id", "int", pk=True, nullable=False),
            C("cust_id", "int", ref="dbon_customer(cust_id)"),
            C("emp_id", "int", ref="dbon_emp(emp_id)"),
            C("order_date", "timestamp"),
            C("amount", "decimal", (12, 2)),
            C("order_status", "varchar", (20,)),
        ],
    }


SURNAMES = "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄변채원천방공현함염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉사부"
GIVEN = "민서준도윤하은지우현수예진영호성재연유정훈희경태동규상혁승아다나보미소채원주혜석철용범기찬우빈건율"
DEPTS = [
    "경영지원팀", "인사팀", "재무팀", "영업1팀", "영업2팀", "마케팅팀", "개발1팀", "개발2팀", "품질관리팀",
    "데이터팀", "고객지원팀", "구매팀", "법무팀", "전략기획팀", "보안팀", "인프라팀", "디자인팀", "교육팀",
]
CITIES = {
    "서울특별시": ["강남구", "서초구", "송파구", "마포구", "종로구", "영등포구", "용산구", "성동구"],
    "부산광역시": ["해운대구", "수영구", "부산진구", "동래구"],
    "대구광역시": ["수성구", "중구", "달서구"],
    "인천광역시": ["연수구", "남동구", "부평구"],
    "광주광역시": ["서구", "북구", "광산구"],
    "대전광역시": ["유성구", "서구", "중구"],
    "경기도": ["성남시 분당구", "수원시 영통구", "고양시 일산동구", "용인시 수지구", "화성시"],
    "제주특별자치도": ["제주시", "서귀포시"],
}
ROADS = ["테헤란로", "중앙로", "세종대로", "한강대로", "해운대로", "대학로", "판교역로", "월드컵로", "경인로", "번영로"]
DOMAINS = ["example.com", "test.co.kr", "sample.net", "mail.example.org"]
GRADES = ["VIP", "GOLD", "SILVER", "BRONZE"]
ORDER_STATUS = ["주문완료", "결제완료", "배송중", "배송완료", "취소", "반품"]
MEMOS = ["재택근무 중", "육아휴직 복귀 예정", "프로젝트 리더", "신입 교육 담당", "자격증 보유: 정보처리기사",
         "해외 파견", "TF 참여", "야간 당직 담당", "멘토", "특이사항 없음"]


class _Gen:
    def __init__(self, seed: int | None):
        self.r = random.Random(seed)

    def name(self) -> str:
        n = self.r.choice((1, 2, 2, 2))
        return self.r.choice(SURNAMES) + "".join(self.r.choice(GIVEN) for _ in range(n))

    def email(self, prefix: str, i: int) -> str | None:
        if self.r.random() < 0.05:
            return None
        return f"{prefix}{i:06d}@{self.r.choice(DOMAINS)}"

    def phone(self) -> str | None:
        if self.r.random() < 0.05:
            return None
        return f"010-{self.r.randint(1000, 9999)}-{self.r.randint(1000, 9999)}"

    def date(self, start: date, end: date) -> date:
        return start + timedelta(days=self.r.randint(0, (end - start).days))

    def ts(self, start: datetime, end: datetime) -> datetime:
        return start + timedelta(seconds=self.r.randint(0, int((end - start).total_seconds())))

    def money(self, lo: int, hi: int, step: int = 1) -> Decimal:
        return Decimal(self.r.randrange(lo, hi, step)).quantize(Decimal("0.01"))

    def address(self) -> str:
        city = self.r.choice(list(CITIES))
        return f"{city} {self.r.choice(CITIES[city])} {self.r.choice(ROADS)} {self.r.randint(1, 999)}"


def generate(rows: int, seed: int | None = None) -> list[Table]:
    g = _Gen(seed)
    schema = _schema()
    n_dept = max(5, rows // 20)
    t0, t1 = datetime(2020, 1, 1), datetime(2026, 12, 31, 23, 59, 59)

    dept = []
    for i in range(1, n_dept + 1):
        base = DEPTS[(i - 1) % len(DEPTS)]
        name = base if i <= len(DEPTS) else f"{base}{(i - 1) // len(DEPTS) + 1}"
        city = g.r.choice(list(CITIES))
        dept.append((i, name, city, g.ts(t0, t1)))

    emp = []
    for i in range(1, rows + 1):
        hire = g.date(date(2005, 1, 1), date(2026, 6, 30))
        emp.append((
            i,
            g.r.randint(1, n_dept),
            g.name(),
            g.email("emp", i),
            g.phone(),
            g.r.choice("MF"),
            g.date(date(1960, 1, 1), date(2003, 12, 31)),
            hire,
            g.money(30_000_000, 120_000_001, 10_000),
            "Y" if g.r.random() < 0.9 else "N",
            g.r.choice(MEMOS) if g.r.random() < 0.3 else None,
            g.ts(t0, t1),
        ))

    cust = []
    for i in range(1, rows + 1):
        cust.append((
            i,
            g.name(),
            g.email("cust", i),
            g.phone(),
            g.address() if g.r.random() < 0.95 else None,
            g.r.choices(GRADES, weights=(5, 15, 30, 50))[0],
            g.date(date(2015, 1, 1), date(2026, 6, 30)),
        ))

    orders = []
    for i in range(1, rows + 1):
        orders.append((
            i,
            g.r.randint(1, rows),
            g.r.randint(1, rows),
            g.ts(t0, t1),
            g.money(1_000, 5_000_001, 100),
            g.r.choices(ORDER_STATUS, weights=(10, 15, 15, 50, 6, 4))[0],
        ))

    data = {"dbon_dept": dept, "dbon_emp": emp, "dbon_customer": cust, "dbon_orders": orders}
    return [Table(name, schema[name], data[name]) for name in schema]
