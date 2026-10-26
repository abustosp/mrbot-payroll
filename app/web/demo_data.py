"""Datos de demostracion y contratos de lectura para la interfaz web.

La capa web no ejecuta reglas de liquidacion. Este modulo solo expone un
repositorio de lectura con datos de ejemplo para que la interfaz pueda
desarrollarse y probarse sin una base de datos real.

Punto de integracion con SQLAlchemy
-----------------------------------
Cuando los modelos de ``app/database/models`` esten disponibles, implementar
un repositorio con la misma interfaz publica que :class:`DemoDataStore`
(metodos ``list_*``/``get_*``/``dashboard_metrics``) y registrarlo en
``app.state.payroll_data_source`` o mediante
``app.dependency_overrides[get_data_source]``. Ver ``app/web/dependencies.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any

D = Decimal


@dataclass(slots=True)
class Company:
    id: str
    name: str
    cuit: str
    city: str
    province: str
    activity: str
    agreement: str
    employee_count: int
    status: str = "active"


@dataclass(slots=True)
class Employee:
    id: str
    name: str
    cuil: str
    file_number: str
    company_id: str
    company_name: str
    category: str
    agreement: str
    hire_date: date
    salary: Decimal
    status: str = "active"
    email: str = ""
    phone: str = ""


@dataclass(slots=True)
class Agreement:
    id: str
    code: str
    name: str
    scope: str
    categories: list[str]
    valid_from: date
    status: str
    formula_count: int
    document_count: int
    summary: str = ""


@dataclass(slots=True)
class PayrollConcept:
    code: str
    name: str
    kind: str
    amount: Decimal
    quantity: Decimal = D("1")
    unit: str = "mes"


@dataclass(slots=True)
class PayrollEmployeeResult:
    employee_id: str
    employee_name: str
    cuil: str
    gross: Decimal
    deductions: Decimal
    net: Decimal


@dataclass(slots=True)
class PayrollRun:
    id: str
    company_id: str
    company_name: str
    period: str
    period_label: str
    type: str
    status: str
    employee_count: int
    gross: Decimal
    deductions: Decimal
    net: Decimal
    employer_cost: Decimal
    created_at: date
    concepts: list[PayrollConcept] = field(default_factory=list)
    employee_results: list[PayrollEmployeeResult] = field(default_factory=list)


@dataclass(slots=True)
class AIProposal:
    id: str
    title: str
    agreement: str
    document: str
    status: str
    confidence: Decimal
    created_at: date
    summary: str
    rules: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_page: str = ""


@dataclass(slots=True)
class Receipt:
    id: str
    number: str
    company_id: str
    employee_id: str
    period: str
    period_label: str
    net: Decimal
    status: str
    issued_on: date
    employer: dict[str, Any] = field(default_factory=dict)
    employee: dict[str, Any] = field(default_factory=dict)
    items: list[PayrollConcept] = field(default_factory=list)
    remunerative_total: Decimal = D("0.00")
    non_remunerative_total: Decimal = D("0.00")
    deductions_total: Decimal = D("0.00")
    contributions_total: Decimal = D("0.00")

    def to_pdf_context(self) -> dict[str, Any]:
        """Contexto canonico aceptado por ``app.exporters.pdf.receipts``."""

        return {
            "receipt_number": self.number,
            "issue_date": self.issued_on,
            "period": self.period_label,
            "employer": dict(self.employer),
            "employee": dict(self.employee),
            "items": [
                {
                    "code": item.code,
                    "name": item.name,
                    "kind": item.kind,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "amount": item.amount,
                }
                for item in self.items
            ],
            "remunerative_total": self.remunerative_total,
            "non_remunerative_total": self.non_remunerative_total,
            "deductions_total": self.deductions_total,
            "contributions_total": self.contributions_total,
            "net": self.net,
        }


def _sum(items: list[PayrollConcept], kind: str) -> Decimal:
    return sum((item.amount for item in items if item.kind == kind), D("0.00"))


def _build_receipt(
    *,
    receipt_id: str,
    number: str,
    company: Company,
    employee_id: str,
    period: str,
    period_label: str,
    issued_on: date,
    status: str,
    items: list[PayrollConcept],
) -> Receipt:
    employee = _EMPLOYEE_SEEDS[employee_id]
    remunerative = _sum(items, "remunerative")
    non_remunerative = _sum(items, "non_remunerative")
    deductions = _sum(items, "deduction")
    contributions = _sum(items, "contribution")
    net = remunerative + non_remunerative - deductions
    return Receipt(
        id=receipt_id,
        number=number,
        company_id=company.id,
        employee_id=employee.id,
        period=period,
        period_label=period_label,
        net=net,
        status=status,
        issued_on=issued_on,
        employer={
            "name": company.name,
            "cuit": company.cuit,
            "address": f"{company.city}, {company.province}",
            "activity": company.activity,
        },
        employee={
            "name": employee.name,
            "cuil": employee.cuil,
            "file_number": employee.file_number,
            "category": employee.category,
            "hire_date": employee.hire_date,
            "agreement": employee.agreement,
        },
        items=items,
        remunerative_total=remunerative,
        non_remunerative_total=non_remunerative,
        deductions_total=deductions,
        contributions_total=contributions,
    )


def _seed_companies() -> list[Company]:
    return [
        Company(
            id="cmp-andes",
            name="Andes Logística S.A.",
            cuit="30-71234567-8",
            city="Córdoba",
            province="Córdoba",
            activity="Transporte y logística",
            agreement="CCT 130/75",
            employee_count=3,
        ),
        Company(
            id="cmp-pampa",
            name="Pampa Alimentos S.R.L.",
            cuit="30-70987654-3",
            city="Rosario",
            province="Santa Fe",
            activity="Industria alimenticia",
            agreement="CCT 130/75",
            employee_count=3,
        ),
        Company(
            id="cmp-sur",
            name="Servicios del Sur S.A.S.",
            cuit="30-71555111-2",
            city="Neuquén",
            province="Neuquén",
            activity="Servicios petroleros",
            agreement="CCT 260/75",
            employee_count=1,
        ),
    ]


def _seed_employees() -> list[Employee]:
    return [
        Employee(
            id="emp-001",
            name="María Fernanda Gómez",
            cuil="27-30111222-4",
            file_number="A-001",
            company_id="cmp-andes",
            company_name="Andes Logística S.A.",
            category="Administrativa A",
            agreement="CCT 130/75",
            hire_date=date(2018, 3, 12),
            salary=D("1850000.00"),
            email="maria.gomez@example.com",
            phone="+54 351 555-0101",
        ),
        Employee(
            id="emp-002",
            name="Juan Carlos Pérez",
            cuil="20-28444555-6",
            file_number="A-002",
            company_id="cmp-andes",
            company_name="Andes Logística S.A.",
            category="Chofer",
            agreement="CCT 130/75",
            hire_date=date(2015, 7, 1),
            salary=D("1720000.00"),
            email="juan.perez@example.com",
            phone="+54 351 555-0102",
        ),
        Employee(
            id="emp-003",
            name="Lucía Benítez",
            cuil="27-34555666-7",
            file_number="A-003",
            company_id="cmp-andes",
            company_name="Andes Logística S.A.",
            category="Administrativa B",
            agreement="CCT 130/75",
            hire_date=date(2022, 11, 21),
            salary=D("1420000.00"),
            email="lucia.benitez@example.com",
            phone="+54 351 555-0103",
        ),
        Employee(
            id="emp-004",
            name="Santiago Ríos",
            cuil="20-31222333-8",
            file_number="P-004",
            company_id="cmp-pampa",
            company_name="Pampa Alimentos S.R.L.",
            category="Operario",
            agreement="CCT 130/75",
            hire_date=date(2019, 2, 18),
            salary=D("1560000.00"),
            email="santiago.rios@example.com",
        ),
        Employee(
            id="emp-005",
            name="Ana Paula Medina",
            cuil="27-36777888-9",
            file_number="P-005",
            company_id="cmp-pampa",
            company_name="Pampa Alimentos S.R.L.",
            category="Supervisora",
            agreement="CCT 130/75",
            hire_date=date(2020, 9, 1),
            salary=D("2100000.00"),
            email="ana.medina@example.com",
        ),
        Employee(
            id="emp-006",
            name="Diego Ángel Ferreyra",
            cuil="20-29888999-1",
            file_number="S-006",
            company_id="cmp-sur",
            company_name="Servicios del Sur S.A.S.",
            category="Técnico",
            agreement="CCT 260/75",
            hire_date=date(2016, 5, 23),
            salary=D("2450000.00"),
            email="diego.ferreyra@example.com",
        ),
        Employee(
            id="emp-007",
            name="Carla Ortiz",
            cuil="27-40111222-3",
            file_number="P-007",
            company_id="cmp-pampa",
            company_name="Pampa Alimentos S.R.L.",
            category="Administrativa B",
            agreement="CCT 130/75",
            hire_date=date(2023, 4, 10),
            salary=D("1380000.00"),
            status="inactive",
            email="carla.ortiz@example.com",
        ),
    ]


_EMPLOYEE_SEEDS: dict[str, Employee] = {employee.id: employee for employee in _seed_employees()}
_COMPANY_SEEDS: list[Company] = _seed_companies()


def _seed_agreements() -> list[Agreement]:
    return [
        Agreement(
            id="cct-130-75",
            code="CCT 130/75",
            name="Empleados de Comercio",
            scope="Nacional · Comercio y servicios",
            categories=["Administrativo A", "Administrativo B", "Vendedor", "Maestranza"],
            valid_from=date(2026, 4, 1),
            status="active",
            formula_count=12,
            document_count=4,
            summary=(
                "Convenio base para el personal de comercio. Incluye escala salarial, "
                "antigüedad, presentismo y adicionales por caja."
            ),
        ),
        Agreement(
            id="cct-260-75",
            code="CCT 260/75",
            name="Transporte de Cargas",
            scope="Nacional · Transporte",
            categories=["Chofer de camión", "Ayudante", "Técnico"],
            valid_from=date(2026, 3, 1),
            status="active",
            formula_count=9,
            document_count=3,
            summary=(
                "Régimen de transporte de cargas con adicionales por kilómetro, "
                "pernocte y horas extraordinarias."
            ),
        ),
        Agreement(
            id="cct-40-89",
            code="CCT 40/89",
            name="Industria Alimenticia",
            scope="Nacional · Alimentos",
            categories=["Operario", "Operario especializado", "Supervisor"],
            valid_from=date(2026, 2, 1),
            status="review",
            formula_count=7,
            document_count=2,
            summary=(
                "Convenio en revisión normativa. Las propuestas de IA se encuentran "
                "pendientes de validación profesional."
            ),
        ),
    ]


def _seed_payrolls() -> list[PayrollRun]:
    september_results = [
        PayrollEmployeeResult(
            "emp-001", "María Fernanda Gómez", "27-30111222-4", D("2202500.00"), D("454850.00"), D("1747650.00")
        ),
        PayrollEmployeeResult(
            "emp-002", "Juan Carlos Pérez", "20-28444555-6", D("2121400.00"), D("420096.00"), D("1701304.00")
        ),
        PayrollEmployeeResult(
            "emp-003", "Lucía Benítez", "27-34555666-7", D("1565550.00"), D("247577.00"), D("1317973.00")
        ),
        PayrollEmployeeResult(
            "emp-004", "Santiago Ríos", "20-31222333-8", D("1720000.00"), D("359600.00"), D("1360400.00")
        ),
        PayrollEmployeeResult(
            "emp-005", "Ana Paula Medina", "27-36777888-9", D("2300000.00"), D("540000.00"), D("1760000.00")
        ),
        PayrollEmployeeResult(
            "emp-006", "Diego Ángel Ferreyra", "20-29888999-1", D("2650000.00"), D("620000.00"), D("2030000.00")
        ),
    ]
    september_concepts = [
        PayrollConcept("SUELDO_BASICO", "Sueldo básico", "remunerative", D("9850000.00")),
        PayrollConcept("ANTIGUEDAD", "Antigüedad", "remunerative", D("1180000.00")),
        PayrollConcept("PRESENTISMO", "Presentismo", "remunerative", D("492500.00")),
        PayrollConcept("HORAS_50", "Horas extras al 50%", "remunerative", D("320000.00")),
        PayrollConcept("APORTE_JUB", "Aporte jubilatorio", "deduction", D("1286500.00")),
        PayrollConcept("APORTE_OS", "Aporte obra social", "deduction", D("350850.00")),
        PayrollConcept("GANANCIAS", "Retención de Ganancias", "deduction", D("520000.00")),
        PayrollConcept("CONTRIB_JUB", "Contribución jubilatoria", "contribution", D("1960000.00")),
        PayrollConcept("CONTRIB_OS", "Contribución obra social", "contribution", D("1010000.00")),
        PayrollConcept("CONTRIB_ART", "Contribución ART", "contribution", D("410000.00")),
    ]
    return [
        PayrollRun(
            id="pay-2026-09",
            company_id="cmp-andes",
            company_name="Andes Logística S.A.",
            period="2026-09",
            period_label="Septiembre 2026",
            type="Mensual",
            status="review",
            employee_count=6,
            gross=D("12559450.00"),
            deductions=D("2642123.00"),
            net=D("9917327.00"),
            employer_cost=D("15009450.00"),
            created_at=date(2026, 9, 30),
            concepts=september_concepts,
            employee_results=september_results,
        ),
        PayrollRun(
            id="pay-2026-08",
            company_id="cmp-andes",
            company_name="Andes Logística S.A.",
            period="2026-08",
            period_label="Agosto 2026",
            type="Mensual",
            status="closed",
            employee_count=6,
            gross=D("11842000.00"),
            deductions=D("2501800.00"),
            net=D("9340200.00"),
            employer_cost=D("14204500.00"),
            created_at=date(2026, 8, 31),
            concepts=[],
            employee_results=september_results,
        ),
        PayrollRun(
            id="pay-2026-10",
            company_id="cmp-pampa",
            company_name="Pampa Alimentos S.R.L.",
            period="2026-10",
            period_label="Octubre 2026",
            type="Mensual",
            status="draft",
            employee_count=0,
            gross=D("0.00"),
            deductions=D("0.00"),
            net=D("0.00"),
            employer_cost=D("0.00"),
            created_at=date(2026, 10, 26),
            concepts=[],
            employee_results=[],
        ),
        PayrollRun(
            id="pay-2026-07",
            company_id="cmp-sur",
            company_name="Servicios del Sur S.A.S.",
            period="2026-07",
            period_label="Julio 2026",
            type="Mensual",
            status="approved",
            employee_count=1,
            gross=D("2650000.00"),
            deductions=D("620000.00"),
            net=D("2030000.00"),
            employer_cost=D("3180000.00"),
            created_at=date(2026, 7, 31),
            concepts=[],
            employee_results=[],
        ),
    ]


def _seed_proposals() -> list[AIProposal]:
    return [
        AIProposal(
            id="prop-001",
            title="Adicional por antigüedad",
            agreement="CCT 130/75",
            document="Acuerdo paritario abril 2026",
            status="in_review",
            confidence=D("92.5"),
            created_at=date(2026, 10, 24),
            summary=(
                "La IA detectó un adicional del 1% del sueldo básico por cada año "
                "de antigüedad computable, con vigencia desde abril de 2026."
            ),
            rules=[
                "Adicional = sueldo_basico × años_antiguedad × 0,01",
                "Aplica a categorías Administrativo A, Administrativo B y Vendedor.",
                "Redondeo HALF_UP a dos decimales.",
            ],
            warnings=["Validar la base remunerativa antes de publicar la regla."],
            source_page="Artículo 12, página 4",
        ),
        AIProposal(
            id="prop-002",
            title="Escala salarial abril 2026",
            agreement="CCT 130/75",
            document="Resolución homologatoria 45/2026",
            status="draft",
            confidence=D("87.0"),
            created_at=date(2026, 10, 22),
            summary=(
                "Propuesta de actualización de la escala básica para las cuatro "
                "categorías del convenio, con retroactividad al 1 de abril."
            ),
            rules=[
                "Actualizar básicos por categoría según Anexo I.",
                "Generar diferencias retroactivas para abril, mayo y junio.",
            ],
            warnings=["Falta confirmar el alcance retroactivo con el estudio contable."],
            source_page="Anexo I, página 9",
        ),
        AIProposal(
            id="prop-003",
            title="Presentismo y ausencias",
            agreement="CCT 130/75",
            document="Acta complementaria septiembre 2026",
            status="approved",
            confidence=D("96.0"),
            created_at=date(2026, 9, 18),
            summary=(
                "Regla de presentismo mensual con descuento proporcional por "
                "ausencias injustificadas y exclusión de licencias legales."
            ),
            rules=[
                "Presentismo = 5% del sueldo básico.",
                "No se descuenta por licencia por enfermedad documentada.",
            ],
            warnings=[],
            source_page="Cláusula 3, página 2",
        ),
        AIProposal(
            id="prop-004",
            title="Adicional por pernocte",
            agreement="CCT 260/75",
            document="Acuerdo salarial transporte 2026",
            status="rejected",
            confidence=D("68.0"),
            created_at=date(2026, 8, 30),
            summary="Propuesta descartada por falta de fuente normativa verificable.",
            rules=["Adicional por pernocte fuera de convenio."],
            warnings=["La fuente citada no corresponde al CCT 260/75."],
            source_page="Página 17",
        ),
    ]


def _seed_receipts() -> list[Receipt]:
    andes = next(company for company in _COMPANY_SEEDS if company.id == "cmp-andes")
    pampa = next(company for company in _COMPANY_SEEDS if company.id == "cmp-pampa")
    return [
        _build_receipt(
            receipt_id="rec-2026-09-001",
            number="R-2026-09-0001",
            company=andes,
            employee_id="emp-001",
            period="2026-09",
            period_label="Septiembre 2026",
            issued_on=date(2026, 9, 30),
            status="issued",
            items=[
                PayrollConcept("SUELDO_BASICO", "Sueldo básico", "remunerative", D("1850000.00")),
                PayrollConcept("ANTIGUEDAD", "Antigüedad", "remunerative", D("185000.00")),
                PayrollConcept("PRESENTISMO", "Presentismo", "remunerative", D("92500.00")),
                PayrollConcept("VIATICOS", "Viáticos", "non_remunerative", D("75000.00")),
                PayrollConcept("APORTE_JUB", "Aporte jubilatorio", "deduction", D("234025.00")),
                PayrollConcept("APORTE_OS", "Aporte obra social", "deduction", D("63825.00")),
                PayrollConcept("CUOTA_SINDICAL", "Cuota sindical", "deduction", D("37000.00")),
                PayrollConcept("GANANCIAS", "Retención de Ganancias", "deduction", D("120000.00")),
                PayrollConcept("CONTRIB_JUB", "Contribución jubilatoria", "contribution", D("356000.00")),
                PayrollConcept("CONTRIB_OS", "Contribución obra social", "contribution", D("148925.00")),
                PayrollConcept("CONTRIB_ART", "Contribución ART", "contribution", D("74462.50")),
            ],
        ),
        _build_receipt(
            receipt_id="rec-2026-09-002",
            number="R-2026-09-0002",
            company=andes,
            employee_id="emp-002",
            period="2026-09",
            period_label="Septiembre 2026",
            issued_on=date(2026, 9, 30),
            status="issued",
            items=[
                PayrollConcept("SUELDO_BASICO", "Sueldo básico", "remunerative", D("1720000.00")),
                PayrollConcept("ANTIGUEDAD", "Antigüedad", "remunerative", D("206400.00")),
                PayrollConcept("HORAS_50", "Horas extras al 50%", "remunerative", D("150000.00")),
                PayrollConcept("REFRIGERIO", "Refrigerio", "non_remunerative", D("45000.00")),
                PayrollConcept("APORTE_JUB", "Aporte jubilatorio", "deduction", D("228404.00")),
                PayrollConcept("APORTE_OS", "Aporte obra social", "deduction", D("62292.00")),
                PayrollConcept("CUOTA_SINDICAL", "Cuota sindical", "deduction", D("34400.00")),
                PayrollConcept("GANANCIAS", "Retención de Ganancias", "deduction", D("95000.00")),
                PayrollConcept("CONTRIB_JUB", "Contribución jubilatoria", "contribution", D("347000.00")),
                PayrollConcept("CONTRIB_OS", "Contribución obra social", "contribution", D("145348.00")),
                PayrollConcept("CONTRIB_ART", "Contribución ART", "contribution", D("72674.00")),
            ],
        ),
        _build_receipt(
            receipt_id="rec-2026-09-003",
            number="R-2026-09-0003",
            company=andes,
            employee_id="emp-003",
            period="2026-09",
            period_label="Septiembre 2026",
            issued_on=date(2026, 9, 30),
            status="issued",
            items=[
                PayrollConcept("SUELDO_BASICO", "Sueldo básico", "remunerative", D("1420000.00")),
                PayrollConcept("ANTIGUEDAD", "Antigüedad", "remunerative", D("71000.00")),
                PayrollConcept("PRESENTISMO", "Presentismo", "remunerative", D("74550.00")),
                PayrollConcept("APORTE_JUB", "Aporte jubilatorio", "deduction", D("172210.50")),
                PayrollConcept("APORTE_OS", "Aporte obra social", "deduction", D("46966.50")),
                PayrollConcept("CUOTA_SINDICAL", "Cuota sindical", "deduction", D("28400.00")),
                PayrollConcept("CONTRIB_JUB", "Contribución jubilatoria", "contribution", D("262000.00")),
                PayrollConcept("CONTRIB_OS", "Contribución obra social", "contribution", D("109588.50")),
                PayrollConcept("CONTRIB_ART", "Contribución ART", "contribution", D("54794.25")),
            ],
        ),
        _build_receipt(
            receipt_id="rec-2026-10-004",
            number="R-2026-10-0004",
            company=pampa,
            employee_id="emp-004",
            period="2026-10",
            period_label="Octubre 2026",
            issued_on=date(2026, 10, 26),
            status="pending",
            items=[
                PayrollConcept("SUELDO_BASICO", "Sueldo básico", "remunerative", D("1560000.00")),
                PayrollConcept("ANTIGUEDAD", "Antigüedad", "remunerative", D("109200.00")),
                PayrollConcept("APORTE_JUB", "Aporte jubilatorio", "deduction", D("200184.00")),
                PayrollConcept("APORTE_OS", "Aporte obra social", "deduction", D("54586.00")),
            ],
        ),
    ]


def _matches(query: str, *values: Any) -> bool:
    needle = query.strip().casefold()
    if not needle:
        return True
    return any(needle in str(value).casefold() for value in values)


class DemoDataStore:
    """Repositorio de lectura en memoria, aislado por aplicacion."""

    is_demo = True
    source_name = "Datos demo en memoria"
    explanation = (
        "La interfaz usa datos de demostracion. Cuando el repositorio SQLAlchemy "
        "este disponible, reemplace esta fuente mediante app.state.payroll_data_source."
    )

    def __init__(self) -> None:
        self.companies: list[Company] = [replace(company) for company in _COMPANY_SEEDS]
        self.employees: list[Employee] = [
            replace(employee) for employee in _EMPLOYEE_SEEDS.values()
        ]
        self.agreements: list[Agreement] = _seed_agreements()
        self.payrolls: list[PayrollRun] = _seed_payrolls()
        self.proposals: list[AIProposal] = _seed_proposals()
        self.receipts: list[Receipt] = _seed_receipts()

    # -- Empresas ---------------------------------------------------------
    def list_companies(self, query: str = "") -> list[Company]:
        return [
            company
            for company in self.companies
            if _matches(query, company.name, company.cuit, company.city, company.activity)
        ]

    def get_company(self, company_id: str) -> Company | None:
        return next((company for company in self.companies if company.id == company_id), None)

    def employees_for_company(self, company_id: str) -> list[Employee]:
        return [employee for employee in self.employees if employee.company_id == company_id]

    # -- Empleados --------------------------------------------------------
    def list_employees(
        self,
        query: str = "",
        company_id: str = "",
        status: str = "",
    ) -> list[Employee]:
        return [
            employee
            for employee in self.employees
            if (not company_id or employee.company_id == company_id)
            and (not status or employee.status == status)
            and _matches(
                query,
                employee.name,
                employee.cuil,
                employee.file_number,
                employee.category,
                employee.company_name,
            )
        ]

    def get_employee(self, employee_id: str) -> Employee | None:
        return next((employee for employee in self.employees if employee.id == employee_id), None)

    # -- Convenios --------------------------------------------------------
    def list_agreements(self, query: str = "") -> list[Agreement]:
        return [
            agreement
            for agreement in self.agreements
            if _matches(query, agreement.code, agreement.name, agreement.scope)
        ]

    def get_agreement(self, agreement_id: str) -> Agreement | None:
        return next((agreement for agreement in self.agreements if agreement.id == agreement_id), None)

    # -- Liquidaciones ----------------------------------------------------
    def list_payrolls(self, status: str = "", company_id: str = "") -> list[PayrollRun]:
        return [
            payroll
            for payroll in self.payrolls
            if (not status or payroll.status == status)
            and (not company_id or payroll.company_id == company_id)
        ]

    def get_payroll(self, payroll_id: str) -> PayrollRun | None:
        return next((payroll for payroll in self.payrolls if payroll.id == payroll_id), None)

    # -- Propuestas IA ----------------------------------------------------
    def list_proposals(self, status: str = "") -> list[AIProposal]:
        return [
            proposal
            for proposal in self.proposals
            if not status or proposal.status == status
        ]

    def get_proposal(self, proposal_id: str) -> AIProposal | None:
        return next((proposal for proposal in self.proposals if proposal.id == proposal_id), None)

    def set_proposal_status(self, proposal_id: str, status: str) -> AIProposal | None:
        allowed = {"draft", "in_review", "approved", "rejected"}
        if status not in allowed:
            raise ValueError(f"Estado de propuesta no valido: {status}")
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return None
        proposal.status = status
        return proposal

    # -- Recibos ----------------------------------------------------------
    def list_receipts(
        self,
        query: str = "",
        company_id: str = "",
        period: str = "",
        status: str = "",
    ) -> list[Receipt]:
        return [
            receipt
            for receipt in self.receipts
            if (not company_id or receipt.company_id == company_id)
            and (not period or receipt.period == period)
            and (not status or receipt.status == status)
            and _matches(query, receipt.number, receipt.employee.get("name", ""), receipt.employee_id)
        ]

    def get_receipt(self, receipt_id: str) -> Receipt | None:
        return next((receipt for receipt in self.receipts if receipt.id == receipt_id), None)

    def receipt_periods(self) -> list[tuple[str, str]]:
        periods = {
            (receipt.period, receipt.period_label)
            for receipt in self.receipts
        }
        return sorted(periods, reverse=True)

    # -- Dashboard --------------------------------------------------------
    def dashboard_metrics(self) -> dict[str, Any]:
        active_employees = sum(1 for employee in self.employees if employee.status == "active")
        pending_proposals = sum(
            1 for proposal in self.proposals if proposal.status in {"draft", "in_review"}
        )
        in_review = sum(
            1 for payroll in self.payrolls if payroll.status in {"calculated", "review"}
        )
        latest = next(
            (payroll for payroll in self.payrolls if payroll.status != "draft"),
            self.payrolls[0] if self.payrolls else None,
        )
        issued_receipts = sum(1 for receipt in self.receipts if receipt.status == "issued")
        return {
            "companies": len(self.companies),
            "active_employees": active_employees,
            "in_review": in_review,
            "pending_proposals": pending_proposals,
            "issued_receipts": issued_receipts,
            "latest_payroll": latest,
            "total_net": latest.net if latest else D("0.00"),
            "total_gross": latest.gross if latest else D("0.00"),
            "employer_cost": latest.employer_cost if latest else D("0.00"),
        }


__all__ = [
    "AIProposal",
    "Agreement",
    "Company",
    "DemoDataStore",
    "Employee",
    "PayrollConcept",
    "PayrollEmployeeResult",
    "PayrollRun",
    "Receipt",
]
