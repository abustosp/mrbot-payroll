# Contratos de implementacion

Este archivo fija la base compartida para la primera implementacion del `plan.md`.
Los workers de Orca trabajan en el mismo worktree: cada uno edita solo su territorio.

## Base tecnica

- Python 3.11 o superior, FastAPI, SQLAlchemy 2.x, Pydantic 2.x, Alembic, SQLite.
- Dinero y porcentajes siempre con `Decimal`, nunca `float`.
- Fechas con `datetime.date`; vigencias inclusivas `[valid_from, valid_to]`.
- Tests con pytest. Ejecutar con `.venv/bin/python -m pytest`.
- Formato con `.venv/bin/ruff check .` cuando aplique.

## Territorios

| Worker | Puede editar | No puede editar |
|---|---|---|
| foundation | `app/main.py`, `app/config.py`, `app/database/**`, `app/auth/**`, `app/api/**`, `app/modules/companies/**`, `app/modules/employees/**`, `app/modules/agreements/**`, `alembic/**`, `alembic.ini`, `tests/unit/test_api_*.py`, `tests/unit/test_auth_*.py` | otros `app/modules`, `app/core`, `app/jurisdictions`, `app/ai`, `app/exporters`, `app/web` |
| engine | `app/core/payroll_engine/formula_engine.py`, `dependency_resolver.py`, `rounding.py`, `validations.py`, `tests/payroll/test_formula_*.py`, `tests/payroll/test_dependency_*.py` | `types.py`, `__init__.py`, `calculator.py`, `tax_bases.py`, otras carpetas |
| calculator | `app/core/payroll_engine/calculator.py`, `tax_bases.py`, `concepts.py`, `tests/payroll/test_calculator_*.py`, `tests/payroll/test_tax_bases_*.py` | `formula_engine.py`, `dependency_resolver.py`, `rounding.py`, `validations.py`, `types.py`, `__init__.py` |
| argentina | `app/jurisdictions/**`, `app/core/normative/**`, `app/exporters/txt/**`, `tests/jurisdictions/**`, `tests/exporters/test_lsd_*.py` | `app/core/payroll_engine/**`, `app/exporters/pdf/**`, `app/web/**` |
| ai | `app/ai/**`, `tests/ai/**` | resto de `app/**` |
| web | `app/web/**`, `app/exporters/pdf/**`, `tests/unit/test_web_*.py`, `tests/exporters/test_pdf_*.py` | `app/api/**`, `app/database/**`, `app/jurisdictions/**`, `app/ai/**` |
| imports | `app/importers/**`, `tests/importers/**` | `app/modules/**`, `app/api/**`, `app/web/**`, resto de `app/**` |
| infra | `deployment/**`, `.github/**`, `desktop/**`, `README.md`, `docs/OPERATIONS.md` | `app/**`, `tests/**`, `pyproject.toml` |

El coordinador es dueno de `pyproject.toml`, `tests/conftest.py`, `app/core/payroll_engine/types.py`,
`app/core/payroll_engine/__init__.py`, `docs/IMPLEMENTATION_CONTRACTS.md` y de la integracion final.

## Contratos entre modulos

### Formula engine

```python
from app.core.payroll_engine.types import FormulaDefinition, FormulaContext, FormulaResult

evaluate_formula(definition: FormulaDefinition, context: FormulaContext) -> FormulaResult
resolve_dependencies(definitions: list[FormulaDefinition]) -> list[str]
```

`FormulaDefinition` acepta arboles JSON del DSL descripto en `plan.md` seccion 6.2.
`FormulaContext` contiene `variables: dict[str, Decimal]`, `parameters: dict[str, Decimal]`,
`concepts: dict[str, Decimal]`, `functions: dict[str, Callable]` y `period: date`.
`FormulaResult` contiene `value: Decimal`, `trace: list[str]` y `dependencies: set[str]`.
Operadores minimos: add, subtract, multiply, divide, percentage, min, max, round, if,
comparaciones, and/or/not, variable, parameter, concept y constant.

### Calculator

```python
from app.core.payroll_engine.calculator import calculate_payroll

result = calculate_payroll(employee, period, definitions, parameters, novelties=[])
```

El resultado es un diccionario serializable con `items`, `remunerative`, `non_remunerative`,
`deductions`, `contributions`, `gross`, `net`, `employer_cost` y `trace`.
Los importes se serializan como string decimal para no perder precision.

### Corridas SAC / VACATIONS / FINAL

`SUPPORTED_RUN_TYPES = ("MONTHLY", "SAC", "VACATIONS", "FINAL")`. Las corridas
no mensuales usan el motor de settlements (`app/core/payroll_engine/settlements.py`),
nunca formulas mensuales.

- `SAC`: base = mejor `remunerative` de corridas `MONTHLY` persistidas del
  semestre (estados `CALCULATED`/`IN_REVIEW`/`APPROVED`/`CLOSED`); sin
  historial, la base actual del empleado. Meses = meses calendario desde el
  maximo entre ingreso e inicio del semestre hasta el periodo (tope 6).
- `VACATIONS`/`FINAL`: inputs por empleado en novedades `AUXILIARY` del
  periodo (`VAC_DIAS` cantidad de dias, `VAC_PLUS_TASA` tasa opcional como
  `amount`, `LIQ_DIAS_INTEGRACION` cantidad). `FINAL` exige ademas los
  parametros AR `liq_preaviso_meses`, `liq_integracion_dias_base`,
  `liq_vacaciones_dias_base`, `liq_vacaciones_plus_tasa`,
  `liq_antiguedad_meses_por_anio`. Todo faltante es error por empleado.
- Poblacion `FINAL`: desvinculados dentro del periodo; el resto no integra
  la corrida (sin canal de errores). Conceptos requeridos por tipo en
  `SETTLEMENT_CONCEPT_CODES` (misma regla que mensual sin concepto).
- Novedades no consumidas siguen V2-09. No se calculan aportes ni
  contribuciones (igual que `/settlements`); neto igual a bruto.

### Argentina

`app/jurisdictions/argentina/` expone `ArgentinaProvider` con parametros vigentes,
reglas de aportes/contribuciones y validaciones. Los valores legales son datos versionados,
no constantes enterradas en el calculo. El CCT inicial es 130/75, alcance acotado.

### Exports

- `app/exporters/txt/lsd.py`: funciones puras que reciben datos y devuelven `bytes`/`str`,
  con validacion de longitud y codificacion.
- `app/exporters/pdf/receipts.py`: render de recibo HTML a PDF, con fallback claro si
  WeasyPrint no esta disponible.

### API y web

- API bajo `/api/v1`, contratos Pydantic, errores `{"detail": ...}`.
- Web bajo `/`, templates Jinja2, sin logica de negocio duplicada.
- Autenticacion simple por cookie firmada, roles `admin`, `editor`, `viewer`.

### IA

- `app/ai/` no ejecuta formulas ni publica reglas.
- Proveedor abstracto con implementacion mock para tests.
- Propuestas pasan por validacion de schema, dependencias y fuente; estado inicial `draft`.

## Reglas de trabajo

- No editar archivos fuera del territorio asignado.
- No ejecutar `git add`, `git commit`, `git reset` ni cambiar de rama.
- No agregar dependencias a `pyproject.toml`; si falta una, reportarlo.
- No usar red en tests. Todo test debe correr offline.
- Cada cambio no trivial deja al menos un test o autochequeo.
- Al terminar, ejecutar los tests propios y reportar archivos modificados y resultados.
