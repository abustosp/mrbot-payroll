# Plan de desarrollo: Sistema de Liquidación de Sueldos con Inteligencia Artificial
## Payroll Argentina · Multi-jurisdicción · Python · FastAPI · AdminLTE

**Versión del plan:** 1.0  
**Fecha:** 26 de octubre de 2026  
**Arquitectura:** Modular, API-first, extensible y multiplataforma.  
**Modalidades:** Aplicación local (Windows/Linux) y aplicación web (Docker).

---

# 1. Visión general del proyecto

El objetivo es desarrollar un **sistema integral de liquidación de sueldos que combine un motor de cálculo determinístico con inteligencia artificial para interpretar, crear y mantener reglas de liquidación basadas en convenios colectivos de trabajo (CCT)**.

El sistema estará inicialmente orientado a Argentina, pero su arquitectura deberá permitir incorporar nuevas jurisdicciones, incluyendo otros países, sin modificar el núcleo de la aplicación.

La característica diferencial será la posibilidad de que un contador o liquidador incorpore un convenio colectivo, sus acuerdos salariales y sus modificaciones posteriores para que una IA proponga automáticamente las fórmulas, conceptos y parámetros necesarios para liquidar remuneraciones.

La aplicación no deberá depender de la IA para realizar los cálculos cotidianos: **la IA diseña y propone las reglas; el motor de liquidación las ejecuta de manera determinística, verificable y reproducible.**

## 1.1. Objetivos principales

| Objetivo | Descripción | Prioridad |
|---|---|---|
| Liquidación de haberes | Sueldos mensuales, jornales, vacaciones, SAC y liquidaciones finales | Crítica |
| Motor de fórmulas | Fórmulas configurables, versionadas y reutilizables | Crítica |
| IA para convenios | Interpretar CCT y generar propuestas de reglas de liquidación | Crítica |
| Multiempresa | Administrar diferentes empleadores y sus trabajadores | Crítica |
| Multi-CCT | Soportar distintos convenios y categorías profesionales | Crítica |
| Libro Sueldos Digital | Generar archivos TXT compatibles con ARCA | Crítica |
| Recibos de sueldo | Generación de PDF individuales y masivos | Crítica |
| API REST | Integración con sistemas propios y de terceros | Crítica |
| Aplicación local | Ejecutables Windows/Linux con PyInstaller | Alta |
| Aplicación web | Despliegue mediante Docker | Alta |
| Multi-jurisdicción | Reglas nacionales, provinciales e internacionales | Alta |
| MCP | Integración con agentes de inteligencia artificial | Alta |
| Importación de datos | Excel, CSV y otros sistemas de payroll | Alta |
| Contabilidad | Generación automática de asientos de sueldos | Alta |
| Auditoría | Trazabilidad de cálculos, cambios y parámetros | Crítica |
| Actualización normativa | Detección de cambios en convenios y legislación | Alta |
| Liquidación asistida por IA | Explicar cálculos y detectar inconsistencias | Media |
| Portal del empleado | Consultar recibos y documentación | Media |

## 1.2. Usuarios previstos

El sistema deberá contemplar tres escenarios:

**Estudios contables:** múltiples empresas, distintos convenios y liquidaciones periódicas. El objetivo es reducir las tareas manuales y facilitar la supervisión profesional.

**Empresas:** liquidación de sus propios trabajadores, integración con sistemas contables, recursos humanos y control de asistencia.

**Desarrolladores e integradores:** utilización de las capacidades del motor a través de FastAPI, integraciones automáticas, servicios externos y agentes MCP.

Un mismo motor funcional deberá servir a los tres escenarios.

---

# 2. Principios fundamentales de diseño

Recomiendo establecer estos principios desde el inicio del proyecto.

### 2.1. Separación del cálculo y la normativa

El cálculo de remuneraciones no debe estar incorporado directamente en los controladores de FastAPI.

Se necesitan tres elementos independientes:

- **Motor de liquidación:** ejecuta fórmulas, calcula conceptos, aplica redondeos y consolida resultados.
- **Motor normativo:** determina qué reglas corresponden según jurisdicción, convenio, categoría, fechas y características del trabajador.
- **Motor de IA:** interpreta documentos y transforma sus disposiciones en propuestas estructuradas de reglas.

Esta separación permite incorporar nuevos convenios sin desarrollar una nueva versión de la aplicación.

### 2.2. Versionado por vigencia

Cada fórmula, escala salarial, alícuota o parámetro debe tener un período de vigencia.

Por ejemplo, una liquidación correspondiente a julio de 2025 debe poder reproducirse con los parámetros aplicables a ese período, aunque el sistema esté operando en octubre de 2026.

También debe distinguirse entre la fecha de vigencia de una disposición y la fecha en que esa disposición fue publicada o incorporada al sistema. Esto resulta imprescindible para acuerdos salariales retroactivos.

### 2.3. Independencia de infraestructura

El mismo código debe ejecutarse utilizando:

| Componente | Aplicación local | Servidor |
|---|---|---|
| Backend | FastAPI | FastAPI |
| Base de datos | SQLite | PostgreSQL recomendado |
| ORM | SQLAlchemy 2.x | SQLAlchemy 2.x |
| Migraciones | Alembic | Alembic |
| Frontend | AdminLTE | AdminLTE |
| Servidor HTTP | Uvicorn local | Uvicorn / Gunicorn según despliegue |
| Trabajos en segundo plano | Ejecutor local persistente | Workers |
| Almacenamiento | Sistema de archivos | Volumen persistente / S3 |
| IA | API externa o modelo local | API externa o modelo local |
| Distribución | PyInstaller | Docker |

**No debe existir una versión de escritorio y otra web con lógica de negocio diferente.**

### 2.4. Resultados reproducibles

Toda liquidación confirmada deberá conservar:

- Datos originales utilizados.
- Fórmulas y versiones de reglas aplicadas.
- Parámetros normativos y escalas salariales.
- Resultados de cada concepto.
- Bases imponibles.
- Información de aprobación.
- Documentos y archivos generados.

Una liquidación histórica no debe cambiar porque se actualice un convenio o se modifique una fórmula.

### 2.5. IA supervisada, nunca autónoma para cálculos oficiales

El sistema debe impedir que un LLM modifique directamente las reglas de producción sin validaciones.

La inteligencia artificial podrá generar propuestas, identificar conflictos y ejecutar simulaciones, pero las reglas que afecten liquidaciones reales deberán pasar por controles técnicos y aprobación de un usuario autorizado.

Esto es especialmente importante porque el sistema generará información laboral, previsional y tributaria.

---

# 3. Marco normativo argentino

La arquitectura debe contemplar la normativa laboral general, los regímenes especiales, los CCT y las disposiciones aplicables al período de cada liquidación.

Entre las fuentes normativas principales se encuentran la Ley de Contrato de Trabajo 20.744, la legislación de seguridad social, la normativa de retenciones de Ganancias, los convenios colectivos y sus acuerdos modificatorios.

Además, al desarrollar el sistema durante 2026, hay que contemplar las modificaciones introducidas por la **Ley 27.802 de Modernización Laboral, publicada el 6 de marzo de 2026**. [Argentina](https://www.argentina.gob.ar/normativa/nacional/25552/actualizacion?utm_source=chatgpt.com)

## 3.1. Cambios normativos durante el desarrollo

Un ejemplo concreto es el Fondo de Asistencia Laboral (FAL).

ARCA informó el **26 de octubre de 2026** que su implementación se posterga al **1 de diciembre de 2026**, con aplicación desde las declaraciones juradas correspondientes al período devengado diciembre de 2026. [Argentina](https://www.argentina.gob.ar/noticias/prorroga-de-la-implementacion-del-fondo-de-asistencia-laboral?utm_source=chatgpt.com)

Este tipo de situaciones demuestra por qué no conviene programar porcentajes o fechas directamente en las funciones de liquidación.

El sistema debe mantener un catálogo de parámetros con vigencia temporal, fuente normativa y estado de aprobación.

## 3.2. Diferentes dimensiones jurisdiccionales

Es importante distinguir cuatro dimensiones que pueden coexistir:

| Dimensión | Ejemplo | Efectos |
|---|---|---|
| País | Argentina | Legislación laboral y seguridad social |
| Provincia | Misiones, Córdoba, Buenos Aires | Requisitos administrativos y laborales locales |
| Autoridad administrativa | ARCA, autoridad laboral provincial | Presentaciones, registros y documentación |
| Convenio colectivo | Comercio, UOM, UOCRA | Escalas, adicionales, jornadas y condiciones específicas |

El convenio colectivo no debe confundirse con una jurisdicción.

Asimismo, el sistema deberá contemplar convenios de empresa, ramas particulares y regímenes que no se encuentran comprendidos en las reglas generales de la LCT.

La incorporación de otros países se realizará mediante módulos normativos específicos.

# 4. Arquitectura técnica propuesta

Recomiendo utilizar una arquitectura de **monolito modular**, con una API REST central y componentes funcionales independientes.

Esto permite mantener bajos los requerimientos de hardware, simplificar las instalaciones locales y evitar la complejidad de administrar microservicios desde el principio.

La arquitectura deberá permitir extraer servicios independientes en el futuro si el crecimiento del sistema lo requiere.

## 4.1. Diagrama de arquitectura

```text
┌──────────────────────────────────────────────────────────────┐
│                       FRONTEND                               │
│                                                              │
│                    AdminLTE 4 + Jinja2                       │
│                 HTMX + JavaScript + CSS                      │
│                                                              │
│  Dashboard | Empleados | Convenios | Liquidaciones | IA      │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                       FASTAPI                                │
│                                                              │
│  REST API v1       Autenticación       OpenAPI                │
│  Integraciones     MCP Server         Webhooks               │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                   APPLICATION SERVICES                       │
│                                                              │
│  Empresas          Empleados          Convenios              │
│  Novedades         Liquidaciones      Documentos             │
│  Importaciones     Exportaciones      Auditoría              │
└───────────────────────────┬──────────────────────────────────┘
                            │
          ┌─────────────────┼───────────────────┐
          ▼                 ▼                   ▼
┌─────────────────┐ ┌────────────────┐ ┌───────────────────────┐
│  PAYROLL ENGINE │ │   AI ENGINE    │ │   JURISDICTIONS       │
│                 │ │                │ │                       │
│ Fórmulas        │ │ LLM Providers  │ │ Argentina             │
│ Dependencias    │ │ RAG            │ │ Brasil                │
│ Parámetros      │ │ Documentos     │ │ Otras jurisdicciones  │
│ Bases imponibles│ │ Validaciones   │ │                       │
│ Cálculos        │ │ Generación DSL │ │ Normas / Exportadores │
└────────┬────────┘ └────────┬───────┘ └──────────┬────────────┘
         │                   │                    │
         └───────────────────┼────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│                      PERSISTENCIA                            │
│                                                              │
│                    SQLAlchemy ORM                            │
│                    Alembic Migrations                        │
│                                                              │
│                 SQLite / PostgreSQL                          │
│                                                              │
│                Filesystem / S3 / MinIO                       │
└──────────────────────────────────────────────────────────────┘
```

## 4.2. Stack tecnológico

| Componente | Tecnología | Justificación |
|---|---|---|
| Lenguaje | Python | Ecosistema, facilidad de mantenimiento e integración con IA |
| Backend | FastAPI | API REST, OpenAPI, validación y extensibilidad |
| ORM | SQLAlchemy 2.x | Independencia del motor SQL |
| Migraciones | Alembic | Versionado y actualización de esquemas |
| Base local | SQLite | Instalación sencilla y pocos recursos |
| Base servidor | PostgreSQL | Concurrencia y operaciones multiusuario |
| Validaciones | Pydantic | Contratos tipados de entrada y salida |
| Frontend | AdminLTE 4 | Interfaz moderna basada en Bootstrap 5 |
| Templates | Jinja2 | Renderizado desde FastAPI |
| Interactividad | HTMX + JavaScript | Evitar la complejidad de una SPA |
| Motor matemático | Python Decimal | Precisión monetaria |
| Fórmulas | DSL declarativo propio | Ejecución segura y controlada |
| PDF | WeasyPrint | Generación de recibos desde HTML/CSS |
| Excel | openpyxl | Importación y exportación |
| Documentos | PyMuPDF / pdfplumber | Lectura de convenios en PDF |
| IA | Adaptadores a LLM | Independencia del proveedor |
| MCP | MCP Python SDK | Integración con agentes |
| Tests | pytest | Pruebas unitarias, funcionales y de integración |
| Calidad | Ruff + mypy | Estilo y análisis estático |
| Contenedores | Docker Compose | Despliegues web |
| Ejecutables | PyInstaller | Windows y Linux |
| CI/CD | GitHub Actions | Pruebas y compilación automática |

**Recomendación específica para el frontend:** utilizar AdminLTE 4 con Jinja2 y HTMX. AdminLTE 4 está basado en Bootstrap 5 y permite integrarse directamente mediante plantillas HTML, sin necesitar React o Vue. [AdminLTE.IO](https://adminlte.io/docs/?utm_source=chatgpt.com)

Esto reduce el tamaño del proyecto, las dependencias y el costo de mantenimiento.

### SQLite y PostgreSQL

SQLAlchemy será el ORM. Alembic se encargará de las migraciones, no del mapeo objeto-relacional.

Para SQLite deberán considerarse las migraciones mediante `batch_alter_table`, especialmente en operaciones que SQLite no resuelve con un `ALTER TABLE` convencional. [alembic.sqlalchemy.org](https://alembic.sqlalchemy.org/en/latest/batch.html?utm_source=chatgpt.com)

La aplicación deberá utilizar migraciones idénticas a nivel funcional sobre ambos motores, verificadas mediante tests.

---

# 5. Estructura del proyecto

Propongo un único repositorio organizado por dominio funcional.

```text
payroll/
│
├── app/
│   ├── main.py
│   ├── config.py
│   │
│   ├── api/
│   │   ├── v1/
│   │   │   ├── companies.py
│   │   │   ├── employees.py
│   │   │   ├── agreements.py
│   │   │   ├── concepts.py
│   │   │   ├── formulas.py
│   │   │   ├── payroll.py
│   │   │   ├── exports.py
│   │   │   └── ai.py
│   │   └── dependencies.py
│   │
│   ├── core/
│   │   ├── payroll_engine/
│   │   │   ├── calculator.py
│   │   │   ├── formula_engine.py
│   │   │   ├── dependency_resolver.py
│   │   │   ├── rounding.py
│   │   │   ├── tax_bases.py
│   │   │   └── validations.py
│   │   │
│   │   ├── rules/
│   │   │   ├── compiler.py
│   │   │   ├── evaluator.py
│   │   │   ├── validators.py
│   │   │   └── registry.py
│   │   │
│   │   └── normative/
│   │       ├── parameters.py
│   │       ├── effective_dates.py
│   │       └── sources.py
│   │
│   ├── modules/
│   │   ├── companies/
│   │   ├── employees/
│   │   ├── agreements/
│   │   ├── concepts/
│   │   ├── payroll/
│   │   ├── absences/
│   │   ├── vacations/
│   │   ├── accounting/
│   │   └── reports/
│   │
│   ├── jurisdictions/
│   │   ├── base.py
│   │   │
│   │   ├── argentina/
│   │   │   ├── rules/
│   │   │   ├── regulations/
│   │   │   ├── agreements/
│   │   │   ├── income_tax/
│   │   │   ├── social_security/
│   │   │   ├── arca/
│   │   │   │   ├── concepts.py
│   │   │   │   ├── lsd.py
│   │   │   │   ├── validators.py
│   │   │   │   └── specifications/
│   │   │   └── provincial/
│   │   │
│   │   └── brazil/
│   │       └── ...
│   │
│   ├── ai/
│   │   ├── providers/
│   │   ├── document_processing/
│   │   ├── rag/
│   │   ├── rule_generation/
│   │   ├── evaluation/
│   │   └── prompts/
│   │
│   ├── integrations/
│   │   ├── mcp/
│   │   ├── webhooks/
│   │   ├── banks/
│   │   └── accounting/
│   │
│   ├── exporters/
│   │   ├── pdf/
│   │   ├── excel/
│   │   ├── csv/
│   │   ├── txt/
│   │   └── banks/
│   │
│   ├── database/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── models/
│   │
│   ├── web/
│   │   ├── routes/
│   │   ├── templates/
│   │   └── static/
│   │
│   └── workers/
│       ├── jobs.py
│       └── scheduler.py
│
├── alembic/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── payroll/
│   ├── jurisdictions/
│   ├── ai/
│   └── golden_files/
│
├── desktop/
│   ├── launcher.py
│   └── payroll.spec
│
├── deployment/
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── .github/
│   └── workflows/
│       ├── tests.yml
│       ├── docker.yml
│       └── desktop-build.yml
│
├── pyproject.toml
├── alembic.ini
└── README.md
```

Cada módulo debe mantener sus modelos, esquemas, servicios y repositorios.

La estructura permitirá incorporar nuevos países mediante extensiones específicas, sin duplicar los módulos de empleados, liquidaciones o empresas.

---

# 6. Motor de liquidación: componente central

Este será el componente más importante del sistema.

Su diseño determinará tanto la facilidad para incorporar nuevos convenios como la confiabilidad de los resultados.

## 6.1. Conceptos de liquidación

Todo concepto deberá poseer una definición independiente de su fórmula.

Ejemplos:

| Código interno | Concepto | Naturaleza |
|---|---|---|
| SUELDO_BASICO | Sueldo básico | Remunerativo |
| ANTIGUEDAD | Adicional por antigüedad | Según regla aplicable |
| PRESENTISMO | Adicional por asistencia | Según CCT |
| HORAS_50 | Horas extras al 50 % | Remunerativo |
| HORAS_100 | Horas extras al 100 % | Remunerativo |
| SAC | Sueldo anual complementario | Remunerativo |
| APORTE_JUB | Aporte jubilatorio | Descuento |
| APORTE_OS | Aporte obra social | Descuento |
| CUOTA_SINDICAL | Cuota sindical | Descuento |
| GANANCIAS | Retención de Ganancias | Descuento |

**La naturaleza de un concepto no debe determinar por sí sola todas las bases imponibles.**

Por ejemplo, ciertas sumas no remunerativas pueden tener obligaciones específicas de aportes y contribuciones.

Por ello, la definición deberá incluir indicadores independientes de afectación a cada subsistema, con vigencia por período.

## 6.2. Estructura de una fórmula

Cada fórmula deberá contener como mínimo:

| Propiedad | Finalidad |
|---|---|
| ID | Identificador único |
| Código | Identificación funcional |
| Nombre | Descripción |
| Expresión | Operación matemática o lógica |
| Variables | Entradas necesarias |
| Dependencias | Otros conceptos utilizados |
| Condiciones | Requisitos de aplicación |
| Convenio | CCT asociado |
| Categorías | Categorías alcanzadas |
| Jurisdicción | Ámbito de aplicación |
| Vigencia desde/hasta | Período normativo |
| Fuente | Norma o documento que la fundamenta |
| Versión | Identificación de la regla |
| Estado | Borrador, validada, aprobada u obsoleta |
| Redondeo | Política de precisión |
| Tests | Casos conocidos y resultados esperados |

### Ejemplo práctico

Supongamos un adicional ilustrativo del 1 % del básico por cada año de antigüedad.

La fórmula conceptual sería:

```python
antiguedad = sueldo_basico * años_antiguedad * 0.01
```

Sin embargo, **no recomiendo permitir que los usuarios o los LLM ejecuten directamente código Python arbitrario**.

La representación preferida sería un lenguaje de fórmulas declarativo, o DSL.

Por ejemplo:

```json
{
  "code": "ANTIGUEDAD",
  "description": "Adicional por antigüedad",
  "formula": {
    "operator": "multiply",
    "arguments": [
      {"variable": "sueldo_basico"},
      {"variable": "años_antiguedad"},
      {"parameter": "porcentaje_antiguedad"}
    ]
  },
  "conditions": [
    {
      "field": "años_antiguedad",
      "operator": "greater_than",
      "value": 0
    }
  ],
  "rounding": {
    "decimals": 2,
    "mode": "HALF_UP"
  }
}
```

El porcentaje se obtiene de una tabla de parámetros, no de un valor escrito dentro de la fórmula.

*El ejemplo es exclusivamente técnico; no representa una regla universal ni un CCT particular.*

### Ventajas del DSL

Permite realizar validaciones antes de ejecutar la expresión, impedir operaciones peligrosas, identificar dependencias y generar explicaciones comprensibles.

También simplifica la generación de fórmulas mediante LLM, dado que el modelo deberá devolver una estructura JSON validable con Pydantic.

## 6.3. Operaciones que deberá soportar

El motor deberá contar con operadores matemáticos, lógicos, condicionales y temporales.

Entre ellos:

- Suma, resta, multiplicación y división.
- Porcentajes y proporciones.
- Mínimo, máximo y límites.
- Redondeos configurables.
- Condiciones `if/else`.
- Comparaciones y operaciones booleanas.
- Referencias a otros conceptos.
- Consultas de parámetros históricos.
- Cálculos de períodos y antigüedad.
- Prorrateos por horas, días o jornadas.
- Acumulados mensuales, semestrales y anuales.
- Promedios remunerativos.
- Ajustes retroactivos.
- Topes y mínimos imponibles.

Todas las operaciones monetarias deberán realizarse utilizando `Decimal`, evitando errores de precisión binaria.

## 6.4. Resolución de dependencias

Una fórmula puede depender de otras.

Por ejemplo:

```text
Sueldo básico
     │
     ├── Antigüedad
     │
     ├── Presentismo
     │
     └── Horas extras
              │
              ▼
       Remuneración bruta
              │
              ├── Base jubilatoria
              ├── Base obra social
              ├── Base ART
              └── Base de Ganancias
                       │
                       ▼
                  Descuentos
                       │
                       ▼
                    Neto
```

El motor deberá construir un grafo de dependencias, calcular las fórmulas en el orden correcto y detectar referencias circulares.

También deberá poder explicar cómo se obtuvo cada resultado.

Por ejemplo:

```text
Concepto: ANTIGUEDAD

Básico considerado:       $1.000.000
Antigüedad computable:    5 años
Porcentaje anual:         1 %

Cálculo:
1.000.000 × 5 × 0,01

Resultado:                $50.000
```

Esto será fundamental para facilitar la auditoría de liquidaciones.

---

# 7. Inteligencia artificial aplicada a convenios colectivos

Este módulo representa el principal diferencial del proyecto.

La funcionalidad deberá permitir que un usuario incorpore convenios colectivos, acuerdos paritarios y otras disposiciones normativas para generar reglas de liquidación mediante IA.

## 7.1. Flujo propuesto

```text
                  DOCUMENTO ORIGINAL
                           │
                PDF / DOCX / HTML / TXT
                           │
                           ▼
                EXTRACCIÓN DE TEXTO
                           │
                           ▼
              IDENTIFICACIÓN DEL DOCUMENTO
                           │
                  CCT / Acuerdo / Norma
                           │
                           ▼
                 ANÁLISIS MEDIANTE IA
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
       Conceptos        Fórmulas         Escalas
       salariales       y reglas         salariales
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                GENERACIÓN ESTRUCTURADA
                           │
                           ▼
                VALIDACIÓN AUTOMÁTICA
                           │
                           ▼
                SIMULACIÓN DE CÁLCULOS
                           │
                           ▼
                  REVISIÓN HUMANA
                           │
                           ▼
               PUBLICACIÓN DE REGLAS
                           │
                           ▼
                 MOTOR DE LIQUIDACIÓN
```

## 7.2. Ingreso de documentación

El usuario podrá cargar:

- Convenios colectivos completos.
- Acuerdos salariales.
- Escalas salariales.
- Resoluciones homologatorias.
- Actas complementarias.
- Normas legales y reglamentarias.
- Documentación específica de empresas.

También deberá existir la posibilidad de consultar fuentes oficiales.

Para Argentina, una fuente importante será el buscador de convenios colectivos, acuerdos y laudos del organismo laboral nacional, que permite consultar documentación, salarios, escalas y resoluciones homologatorias. [Argentina](https://www.argentina.gob.ar/node/39411?utm_source=chatgpt.com)

No obstante, deberá verificarse el alcance de la publicación, la vigencia del documento y las condiciones de acceso antes de automatizar su descarga.

## 7.3. Funcionalidades del analizador de IA

### A. Identificación de reglas

El sistema intentará identificar:

| Elemento | Información a extraer |
|---|---|
| Categorías | Denominaciones y agrupamientos |
| Salarios básicos | Importes por categoría y período |
| Antigüedad | Fórmula, porcentajes y condiciones |
| Presentismo | Requisitos y forma de cálculo |
| Horas extras | Tratamiento y recargos |
| Jornada | Duración y modalidades |
| Adicionales | Título, zona, función, responsabilidad, etc. |
| Asignaciones | Importes especiales |
| Sumas no remunerativas | Tratamiento normativo específico |
| Aportes sindicales | Condiciones, bases y porcentajes |
| Contribuciones especiales | Obligaciones del empleador |
| Licencias | Reglas convencionales |
| Vigencias | Fechas de aplicación |
| Retroactivos | Períodos alcanzados |

La IA debe identificar tanto las disposiciones explícitas como aquellas que requieran información adicional.

Cuando una regla sea ambigua, deberá marcarse como pendiente y no completarse mediante suposiciones.

### B. Generación de fórmulas

Una vez extraídas las reglas, el LLM deberá convertirlas al DSL definido anteriormente.

Cada propuesta incluirá la fórmula, variables, condiciones, fundamento normativo, fecha de vigencia y tests sugeridos.

### C. Actualización de convenios

El sistema deberá permitir comparar distintas versiones de documentación.

Por ejemplo:

```text
Convenio: CCT XX/YYYY

Versión anterior:
Adicional A = fórmula anterior

Nuevo acuerdo:
Adicional A = fórmula modificada

Resultado:
  - Se detectó una modificación.
  - Se identificó su fecha de vigencia.
  - Se generó una nueva versión de la regla.
  - Se conservaron las versiones anteriores.
  - Se detectaron los períodos potencialmente afectados.
```

La aplicación también deberá identificar si una nueva escala salarial corresponde aplicarla retroactivamente.

### D. Detección de diferencias

El usuario podrá comparar una liquidación generada con las nuevas reglas contra una liquidación anterior.

Ejemplo:

| Concepto | Anterior | Recalculado | Diferencia |
|---|---:|---:|---:|
| Básico | $1.000.000 | $1.100.000 | $100.000 |
| Antigüedad | $50.000 | $55.000 | $5.000 |
| Presentismo | $80.000 | $88.000 | $8.000 |
| Total ilustrativo | $1.130.000 | $1.243.000 | $113.000 |

Los resultados permitirán generar conceptos de diferencias salariales, sujetos a su tratamiento legal correspondiente.

## 7.4. RAG y trazabilidad normativa

Recomiendo incorporar RAG para que las respuestas se basen en documentos identificables.

Cada regla generada deberá conservar una referencia a:

```json
{
  "source": {
    "document_id": "cct_xx",
    "document_version": "2026-10",
    "page": 12,
    "article": "Articulo 15",
    "content_hash": "sha256:..."
  }
}
```

La interfaz deberá permitir seleccionar una regla y visualizar directamente el artículo o fragmento que fundamenta su cálculo.

También deberá diferenciar entre el convenio original, acuerdos modificatorios, homologaciones y criterios internos de liquidación.

## 7.5. Validaciones automáticas de IA

Antes de permitir utilizar una fórmula, el sistema deberá verificar:

| Control | Resultado esperado |
|---|---|
| Sintaxis | DSL válido |
| Variables | Todas existen y son del tipo correcto |
| Dependencias | No existen ciclos |
| Unidades | Porcentajes e importes correctamente interpretados |
| Vigencia | Períodos definidos |
| Fuente | Documento y fragmento identificados |
| Compatibilidad | No existen conflictos no resueltos |
| Resultados | Tests matemáticos satisfactorios |
| Comparación | Diferencias frente a reglas vigentes |
| Aprobación | Usuario autorizado confirmó la regla |

Una fórmula no debe considerarse correcta únicamente porque el LLM indique un alto nivel de confianza.

### Validación profesional

La publicación de nuevas reglas deberá quedar restringida a usuarios autorizados.

Los cambios de mayor riesgo, como el carácter remunerativo, las bases imponibles o el tratamiento de indemnizaciones, deberían requerir una revisión reforzada.

---

# 8. Administración de convenios colectivos

Este módulo debe funcionar como un repositorio normativo estructurado.

## 8.1. Modelo de datos

Cada convenio deberá incluir:

```text
Convenio colectivo
│
├── Identificación
│   ├── Número
│   ├── Año
│   ├── Actividad
│   └── Ámbito
│
├── Categorías
│   ├── Categoría A
│   ├── Categoría B
│   └── Categoría C
│
├── Escalas salariales
│   ├── Vigencia 01
│   ├── Vigencia 02
│   └── Vigencia 03
│
├── Conceptos
│   ├── Básico
│   ├── Antigüedad
│   ├── Presentismo
│   └── Adicionales
│
├── Fórmulas
│   ├── Versiones
│   ├── Condiciones
│   └── Dependencias
│
├── Documentos
│   ├── CCT original
│   ├── Acuerdos
│   └── Homologaciones
│
└── Historial de cambios
```

## 8.2. Reglas de selección y precedencia

Para seleccionar las reglas aplicables, el sistema deberá considerar:

1. País y régimen laboral.
2. Convenio aplicable a la relación laboral.
3. Ámbito de actividad, rama y territorio.
4. Categoría profesional.
5. Tipo de contratación.
6. Fecha de devengamiento.
7. Condiciones particulares del trabajador.
8. Modificaciones normativas aplicables.
9. Configuraciones empresariales válidas.

No conviene utilizar una regla automática simplista de que el convenio más reciente siempre reemplaza al anterior.

Deben modelarse los ámbitos de aplicación y las relaciones entre normas, ya que una modificación puede afectar solamente algunas disposiciones.

## 8.3. Catálogo inicial

Para el lanzamiento recomiendo:

**Primer convenio:** Empleados de Comercio, CCT 130/75, acotado a categorías y situaciones laborales definidas.

**Segundo convenio:** uno con estructura de cálculo significativamente diferente, como UOCRA o UOM, después de analizar los requisitos de sus regímenes específicos.

Esto permitirá comprobar que el sistema es verdaderamente configurable y que no fue desarrollado exclusivamente para un convenio.

No intentaría implementar veinte convenios antes de estabilizar el motor de liquidación.

---

# 9. Gestión de empresas y trabajadores

## 9.1. Empresas

Cada empresa deberá contar con una configuración independiente.

Datos principales:

- Identificación fiscal.
- Razón social.
- Domicilios y establecimientos.
- Actividad económica.
- Jurisdicciones.
- Convenios aplicables.
- ART.
- Obra social y configuraciones previsionales.
- Tipo de empleador y encuadramientos.
- Políticas de liquidación.
- Datos bancarios.
- Parámetros de generación de documentos.

En modalidad multiempresa, la información deberá estar separada lógicamente mediante identificadores de organización y empresa.

## 9.2. Trabajadores

Además de los datos personales y laborales habituales, es conveniente diseñar un historial de la relación laboral.

Por ejemplo:

```text
Empleado
│
├── Datos personales
├── Identificación fiscal
├── Datos bancarios
│
├── Relaciones laborales
│   ├── Empresa
│   ├── Fecha de ingreso
│   ├── Antigüedad reconocida
│   ├── Modalidad de contratación
│   └── Estado
│
├── Historial contractual
│   ├── Convenio
│   ├── Categoría
│   ├── Jornada
│   └── Remuneración pactada
│
├── Novedades
│   ├── Ausencias
│   ├── Horas extras
│   ├── Licencias
│   └── Adelantos
│
├── Liquidaciones
├── Recibos
└── Documentos
```

Es importante conservar los cambios históricos de categoría, jornada, convenio y remuneración.

Una liquidación anterior debe utilizar la información contractual vigente para su período.

## 9.3. Novedades

El módulo de novedades deberá permitir ingresar datos individualmente o de forma masiva.

Ejemplos:

| Novedad | Unidad |
|---|---|
| Horas extras | Horas |
| Ausencias | Días u horas |
| Licencia por enfermedad | Días |
| Vacaciones | Días |
| Adelantos | Importe |
| Comisiones | Importe |
| Bonificaciones | Importe |
| Embargos | Importe o fórmula |
| Suspensiones | Días |
| Incapacidades | Períodos |

Las novedades deberán conservar tanto la fecha del hecho como el período al que se imputan.

---

# 10. Proceso completo de liquidación

## 10.1. Estados de una liquidación

Recomiendo implementar el siguiente flujo:

```text
BORRADOR
   │
   ▼
VALIDANDO
   │
   ├──── ERROR
   │
   ▼
CALCULADA
   │
   ▼
EN REVISIÓN
   │
   ├──── REQUIERE CORRECCIONES
   │
   ▼
APROBADA
   │
   ▼
CERRADA
   │
   ▼
DOCUMENTOS GENERADOS
```

Las liquidaciones cerradas deberán ser inmutables.

Cualquier corrección posterior se realizará mediante liquidaciones complementarias, de ajuste o mediante un procedimiento de reapertura debidamente auditado cuando corresponda.

## 10.2. Tipos de liquidaciones

| Tipo | Alcance |
|---|---|
| Mensual | Liquidación ordinaria |
| Quincenal | Trabajadores quincenalizados |
| Semanal | Liquidación semanal |
| Jornal | Remuneraciones por jornal |
| SAC | Aguinaldo |
| Vacaciones | Adelantos y liquidaciones vacacionales |
| Final | Extinción laboral |
| Retroactiva | Diferencias de períodos anteriores |
| Complementaria | Ajustes y pagos adicionales |
| Simulación | Cálculos sin efectos reales |

El motor deberá permitir varias liquidaciones dentro de un mismo período.

## 10.3. Liquidación masiva

Para estudios contables será importante procesar todos los empleados de una empresa mediante una operación.

El procedimiento recomendado es:

```text
Seleccionar empresa y período
             │
             ▼
Obtener trabajadores activos
             │
             ▼
Cargar novedades
             │
             ▼
Determinar reglas aplicables
             │
             ▼
Calcular todos los empleados
             │
             ▼
Validaciones automáticas
             │
             ▼
Mostrar resumen de liquidación
             │
             ▼
Revisión y aprobación
             │
             ▼
Generar recibos y exportaciones
```

Los cálculos deberán ejecutarse mediante trabajos persistentes.

No utilizaría `FastAPI BackgroundTasks` como mecanismo principal para procesos importantes de liquidación masiva, ya que se necesita garantizar persistencia, recuperación ante reinicios y registro de estados.

En instalaciones locales puede utilizarse una cola persistida en SQLite con un único ejecutor. En instalaciones de servidor, workers separados y una cola basada en Redis son una opción apropiada.

---

# 11. Outputs oficiales: Argentina

El sistema deberá generar los archivos necesarios para que el usuario pueda cumplir con las obligaciones laborales y previsionales correspondientes.

**Un punto importante es distinguir entre generar un archivo compatible con un organismo y realizar efectivamente la presentación oficial.**

## 11.1. Libro de Sueldos Digital de ARCA

Según la documentación oficial consultada, el Libro de Sueldos Digital requiere parametrizar los conceptos del empleador y asociarlos con la grilla universal de ARCA. Posteriormente, las liquidaciones y la información registral intervienen en la generación del libro y de la declaración jurada F.931. [Arca](https://arca.gob.ar/LibrodeSueldosDigital/empleadores/intercambio-info.asp?utm_source=chatgpt.com)

Para implementar esta integración deberán desarrollarse dos exportadores diferentes.

### A. TXT de conceptos

Se utiliza para informar la relación entre los conceptos internos del empleador y los conceptos ARCA.

El diseño oficial contempla registros de **195 posiciones**, incluyendo:

- Código del concepto ARCA.
- Código del concepto del empleador.
- Descripción.
- Indicador de repetición.
- Indicadores de aportes y contribuciones correspondientes a los distintos subsistemas.

Los campos y posiciones se encuentran definidos en el diseño oficial de interfaz de conceptos. [Arca](https://arca.gob.ar/LibrodeSueldosDigital/documentos/nuevos/LSDiseInterfazConceptos.pdf?utm_source=chatgpt.com)

### B. TXT de liquidaciones

El diseño de liquidación contempla diferentes tipos de registro:

| Registro | Contenido | Longitud según diseño consultado |
|---|---|---:|
| 01 | Datos referenciales del envío | 35 |
| 02 | Datos generales de liquidación del trabajador | 115 |
| 03 | Conceptos liquidados | 51 |
| 04 | Información para determinar obligaciones del SUSS | 370 |
| 05 | Trabajadores eventuales | 65 |
| 06 | Observaciones adicionales | 108 |

Estas longitudes corresponden al diseño oficial consultado y deberán conservarse como una especificación versionada, no como constantes imposibles de actualizar. [Arca](https://arca.gob.ar/LibrodeSueldosDigital/documentos/nuevos/LSDiseInterfazLiquidacion.pdf?utm_source=chatgpt.com)

La guía oficial establece además que el archivo de liquidación debe ser TXT, sin compresión y con codificación denominada «ANSI». La aplicación deberá controlar explícitamente la codificación, el relleno de campos, los importes y la estructura de cada registro. [Arca](https://www.arca.gob.ar/LibrodeSueldosDigital/documentos/nuevos/G15_interfaz_de_liquidacion_LSD.pdf?utm_source=chatgpt.com)

### Validaciones necesarias

El exportador deberá verificar:

- Longitud exacta de cada registro.
- Tipos de datos y códigos admitidos.
- Orden e integridad de registros.
- CUIT y CUIL.
- Fechas y períodos.
- Códigos de conceptos.
- Cantidad de trabajadores.
- Correspondencia entre conceptos y bases imponibles.
- Tratamiento de SAC y vacaciones.
- Retroactivos y ajustes.
- Datos de situación de revista.
- Compatibilidad con la versión del diseño.

El sistema debería permitir previsualizar el archivo y ejecutar una validación antes de descargarlo.

**Criterio de aceptación:** generar archivos idénticos en estructura a los modelos oficiales y verificar su aceptación con pruebas reales en el servicio de ARCA, usando datos y entornos autorizados.

## 11.2. Relación con F.931

Se propone generar una planilla interna de control que consolide:

| Información | Resultado |
|---|---|
| Remuneración bruta | Por trabajador |
| Bases imponibles | Por subsistema |
| Aportes | Por trabajador y total |
| Contribuciones | Por trabajador y total |
| ART | Según parámetros aplicables |
| Obra social | Bases y aportes |
| Seguridad social | Consolidación |
| Diferencias | Control contra declaraciones |

El archivo de Libro Sueldos Digital será uno de los outputs fundamentales.

La presentación oficial del F.931 y las validaciones definitivas continuarán realizándose mediante los procedimientos habilitados por ARCA, salvo que se incorpore una integración oficial autorizada.

## 11.3. Recibos de sueldo

Generación individual y masiva de recibos PDF.

Para este componente recomiendo utilizar:

**Jinja2 + HTML/CSS + WeasyPrint.**

Permitirá utilizar plantillas, incorporar logos y adaptar los recibos a las necesidades de cada jurisdicción.

El recibo deberá contemplar los requisitos legales aplicables. En Argentina, el artículo 140 de la LCT, conforme a las modificaciones de 2026, también prevé información sobre contribuciones y otros conceptos abonados por el empleador por disposición legal o convencional. [Argentina](https://www.argentina.gob.ar/normativa/nacional/25552/actualizacion?utm_source=chatgpt.com)

Deberán incluirse las opciones de firma, entrega y conservación electrónica que correspondan.

La emisión del PDF no equivale por sí sola a cumplir con todos los requisitos de firma o constancia de entrega.

## 11.4. Otros outputs argentinos

| Output | Descripción | Etapa |
|---|---|---|
| Recibos PDF | Individuales y masivos | MVP |
| TXT conceptos LSD | Parametrización ARCA | MVP |
| TXT liquidaciones LSD | Importación ARCA | MVP |
| Excel de liquidaciones | Detalle por trabajador | MVP |
| Resumen de sueldos | Totales por concepto | MVP |
| Control F.931 | Bases y obligaciones estimadas | MVP |
| Asientos contables | Devengamiento y pagos | Fase 2 |
| Archivos bancarios | Acreditación de haberes | Fase 2 |
| Liquidaciones sindicales | Planillas según entidad | Fase 2 |
| Libro rubricado | Según autoridad local | Fase 2 |
| Retenciones Ganancias | Cálculos y reportes aplicables | MVP/Fase 2 |
| Certificaciones laborales | Según procedimientos oficiales | Fase 3 |
| Reportes gerenciales | Costos laborales | Fase 3 |

Los archivos bancarios, sindicales y de rúbrica deberán implementarse mediante adaptadores específicos, evitando asumir que existe un único formato válido para todas las entidades.

---

# 12. Arquitectura multi-jurisdicción

El diseño del sistema debe contemplar la posibilidad de implementar nuevos países sin reescribir el motor de liquidación.

## 12.1. Interfaz de jurisdicción

Conceptualmente, cada jurisdicción deberá implementar un contrato común.

Ejemplo simplificado:

```python
from typing import Protocol
from datetime import date


class JurisdictionProvider(Protocol):

    code: str

    def get_applicable_rules(
        self,
        employee_id: str,
        period: date,
    ):
        ...

    def get_statutory_parameters(
        self,
        period: date,
    ):
        ...

    def validate_payroll(
        self,
        payroll_id: str,
    ):
        ...

    def get_available_exports(self):
        ...
```

Las reglas de Argentina podrán encargarse de cuestiones como aportes previsionales, obra social, Ganancias y Libro Sueldos Digital.

Un módulo para Brasil podrá implementar posteriormente sus propios conceptos, obligaciones e integraciones.

## 12.2. Ejemplo de extensión

```text
Jurisdicciones
│
├── Argentina
│   ├── Legislación nacional
│   ├── Convenios colectivos
│   ├── Seguridad social
│   ├── Ganancias
│   ├── ARCA
│   └── Requisitos provinciales
│
├── Brasil
│   ├── Legislación laboral
│   ├── Convenios aplicables
│   ├── Seguridad social
│   ├── Tributación
│   └── Exportadores oficiales
│
└── Futuras jurisdicciones
```

No sería correcto intentar resolver todas las diferencias entre países exclusivamente mediante fórmulas matemáticas.

El núcleo de cálculo puede ser común, pero la selección de reglas, el tratamiento fiscal, la seguridad social y los formatos oficiales necesitan componentes propios.

---

# 13. Diseño de base de datos

Recomiendo SQLAlchemy 2.x con modelos tipados y migraciones mediante Alembic.

## 13.1. Entidades principales

| Tabla | Finalidad |
|---|---|
| `organizations` | Organizaciones usuarias |
| `users` | Usuarios del sistema |
| `roles` | Perfiles y permisos |
| `companies` | Empresas empleadoras |
| `establishments` | Establecimientos |
| `employees` | Datos de trabajadores |
| `employment_contracts` | Relaciones laborales |
| `employment_history` | Historial contractual |
| `jurisdictions` | Jurisdicciones disponibles |
| `collective_agreements` | Convenios colectivos |
| `agreement_categories` | Categorías profesionales |
| `salary_scales` | Escalas salariales |
| `payroll_concepts` | Catálogo de conceptos |
| `concept_tax_treatments` | Afectación a bases y subsistemas |
| `formula_definitions` | Definiciones lógicas |
| `formula_versions` | Versiones de fórmulas |
| `normative_parameters` | Parámetros legales |
| `normative_documents` | Documentos fuente |
| `ruleset_versions` | Conjuntos aprobados de reglas |
| `employee_events` | Novedades |
| `payroll_runs` | Procesos de liquidación |
| `payroll_results` | Liquidaciones por trabajador |
| `payroll_items` | Conceptos liquidados |
| `payroll_calculation_traces` | Trazabilidad del cálculo |
| `payroll_approvals` | Aprobaciones |
| `generated_documents` | Documentos emitidos |
| `export_jobs` | Archivos de salida |
| `ai_generations` | Propuestas de IA |
| `audit_logs` | Auditoría |
| `background_jobs` | Trabajos persistentes |

## 13.2. Datos históricos

Los parámetros normativos deberían mantener:

```text
parameter_id
jurisdiction_id
parameter_code
value
valid_from
valid_to
published_at
recorded_at
source_document_id
version
status
```

Esto permitirá conocer qué valor era aplicable en un período y qué información estaba disponible cuando se realizó una liquidación.

En términos técnicos, conviene acercarse a un modelo de **versionado bitemporal** para las reglas normativas.

## 13.3. SQLite y PostgreSQL

### SQLite

Será el motor por defecto.

Configuración recomendada:

```text
journal_mode = WAL
foreign_keys = ON
busy_timeout = 5000
```

Deberá utilizarse una estrategia de escritura controlada, ya que SQLite no está diseñado para manejar la misma concurrencia de escritura que PostgreSQL. [SQLAlchemy Documentation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html?utm_source=chatgpt.com)

### PostgreSQL

Será el motor recomendado para instalaciones multiusuario.

Permitirá manejar de mejor manera múltiples liquidaciones simultáneas, procesos de importación, trabajadores en segundo plano y operaciones concurrentes.

Para ambos motores deben existir pruebas de migraciones y consistencia transaccional.

---

# 14. Frontend con AdminLTE

La interfaz deberá priorizar claridad, velocidad y facilidad de operación.

En un sistema de liquidación de sueldos resulta especialmente importante permitir operaciones masivas sin exigir demasiados pasos.

## 14.1. Organización de pantallas

```text
Dashboard
│
├── Empresas
│   ├── Listado
│   ├── Configuración
│   └── Establecimientos
│
├── Empleados
│   ├── Listado
│   ├── Legajos
│   ├── Contratos
│   └── Importación masiva
│
├── Convenios
│   ├── Convenios disponibles
│   ├── Escalas salariales
│   ├── Conceptos
│   ├── Fórmulas
│   └── Documentos normativos
│
├── Liquidaciones
│   ├── Nueva liquidación
│   ├── Novedades
│   ├── Simulaciones
│   ├── Resultados
│   └── Historial
│
├── Inteligencia artificial
│   ├── Analizar convenio
│   ├── Generar fórmulas
│   ├── Comparar acuerdos
│   └── Revisar propuestas
│
├── Exportaciones
│   ├── Recibos
│   ├── Libro Sueldos Digital
│   ├── Excel / CSV
│   └── Contabilidad
│
└── Administración
    ├── Usuarios
    ├── Configuración
    ├── Integraciones
    └── Auditoría
```

## 14.2. Editor visual de fórmulas

Esta debería ser una de las pantallas más desarrolladas del frontend.

Una propuesta de distribución:

```text
┌─────────────────────────────────────────────────────────────┐
│ EDITOR DE FÓRMULAS                                          │
├─────────────────────────────────────────────────────────────┤
│ Concepto: Adicional por antigüedad                          │
│ Convenio: XX/YYYY                                           │
│ Vigencia: 01/10/2026                                        │
├────────────────────────────────┬────────────────────────────┤
│                                │                            │
│ FÓRMULA                        │ VARIABLES DISPONIBLES       │
│                                │                            │
│ Básico × Años × Porcentaje     │ sueldo_basico              │
│                                │ años_antiguedad            │
│ [ Editor visual ]              │ porcentaje_antiguedad      │
│                                │                            │
├────────────────────────────────┴────────────────────────────┤
│ FUENTE NORMATIVA                                            │
│                                                             │
│ Documento: Acuerdo salarial                                 │
│ Artículo: ...                                               │
│ [Ver documento original]                                    │
├─────────────────────────────────────────────────────────────┤
│ SIMULADOR                                                   │
│                                                             │
│ Básico:       1.000.000                                     │
│ Antigüedad:   5                                             │
│ Porcentaje:   1%                                            │
│                                                             │
│ Resultado:    50.000                                        │
│                                                             │
│ [Simular] [Validar] [Enviar a aprobación]                   │
└─────────────────────────────────────────────────────────────┘
```

Deberá permitir que un usuario ajuste la propuesta de la IA sin necesidad de programar.

---

# 15. API REST e integraciones MCP

La arquitectura API-first permitirá operar el sistema desde otras aplicaciones.

## 15.1. Endpoints REST

Propuesta inicial:

| Método | Endpoint | Funcionalidad |
|---|---|---|
| GET | `/api/v1/companies` | Listar empresas |
| POST | `/api/v1/companies` | Crear empresa |
| GET | `/api/v1/employees` | Consultar trabajadores |
| POST | `/api/v1/employees` | Crear trabajador |
| POST | `/api/v1/employees/import` | Importar trabajadores |
| GET | `/api/v1/agreements` | Consultar convenios |
| POST | `/api/v1/agreements` | Registrar convenio |
| GET | `/api/v1/formulas` | Consultar fórmulas |
| POST | `/api/v1/formulas` | Crear borrador |
| POST | `/api/v1/formulas/{id}/validate` | Validar fórmula |
| POST | `/api/v1/formulas/{id}/approve` | Aprobar fórmula |
| POST | `/api/v1/payroll-runs` | Iniciar liquidación |
| GET | `/api/v1/payroll-runs/{id}` | Consultar estado |
| POST | `/api/v1/payroll-runs/{id}/approve` | Aprobar liquidación |
| POST | `/api/v1/payroll-runs/{id}/exports` | Generar archivos |
| POST | `/api/v1/ai/analyze-agreement` | Analizar convenio |
| GET | `/api/v1/jobs/{id}` | Consultar tarea |

Las operaciones de procesamiento largo deberán devolver un identificador de trabajo.

Ejemplo:

```json
{
  "job_id": "019a...",
  "status": "pending",
  "resource_type": "payroll_run"
}
```

Luego será posible consultar su estado o recibir un webhook cuando finalice.

Deberán implementarse mecanismos de idempotencia para evitar duplicar liquidaciones ante reintentos.

## 15.2. MCP Server

El MCP Server permitirá que un agente externo utilice funciones de la aplicación.

Herramientas posibles:

```text
list_companies
list_employees
get_employee_payroll_history
list_collective_agreements
get_agreement_rules
explain_payroll_concept
simulate_payroll
analyze_collective_agreement
propose_formula
get_payroll_summary
generate_payroll_export
```

Los permisos deberán limitar las acciones disponibles.

Por defecto, un agente podrá consultar información autorizada y generar propuestas o simulaciones.

**No debería poder aprobar una liquidación, publicar fórmulas o modificar datos laborales sin una autorización explícita.**

## 15.3. Proveedores de LLM

El sistema no deberá depender de un único proveedor.

Se recomienda definir un adaptador de modelos con soporte para:

- APIs de modelos comerciales.
- Proveedores compatibles con OpenAI API.
- Modelos autoalojados.
- Modelos locales.
- Configuración independiente por tarea.

Por ejemplo, la extracción de datos estructurados puede utilizar un modelo más económico, mientras que la interpretación de convenios complejos puede utilizar otro de mayor capacidad de razonamiento.

Es conveniente registrar los costos y tokens consumidos por proceso.

---

# 16. Seguridad y auditoría

El sistema manejará información laboral, patrimonial y personal, incluyendo potencialmente datos de salud y afiliación sindical.

En Argentina corresponde contemplar la Ley 25.326 de Protección de Datos Personales y sus obligaciones aplicables. [Argentina](https://www.argentina.gob.ar/normativa/nacional/64790/actualizacion?utm_source=chatgpt.com)

## 16.1. Seguridad

Implementar:

- Autenticación mediante sesiones seguras para el frontend y mecanismos de autorización apropiados para la API.
- Roles y permisos por organización y empresa.
- Protección CSRF en operaciones del frontend.
- Validación de todas las entradas.
- Cifrado de comunicaciones en servidores.
- Gestión segura de credenciales.
- Control de acceso a documentos.
- Backups y recuperación.
- Auditoría de cambios.
- Protección frente a ejecuciones no autorizadas de fórmulas.

### Seguridad de la IA

Se deberán tratar los documentos incorporados como contenido no confiable.

Una instrucción dentro de un convenio o archivo adjunto no podrá modificar el comportamiento del sistema ni otorgar permisos al agente.

También recomiendo que los documentos enviados a proveedores externos no incluyan datos personales de empleados salvo que resulte necesario, exista una base legal apropiada y se haya configurado expresamente su utilización.

## 16.2. Auditoría de liquidaciones

Cada liquidación deberá mantener un registro que permita responder:

**Quién calculó, cuándo, con qué reglas, sobre qué datos y quién aprobó el resultado.**

Ejemplo:

```json
{
  "payroll_id": "12345",
  "employee_id": "987",
  "period": "2026-10",
  "ruleset_version": "1.4.2",
  "calculated_at": "2026-10-26T14:00:00-03:00",
  "status": "approved",
  "inputs_hash": "sha256:...",
  "results_hash": "sha256:...",
  "approved_by": "user_15"
}
```

Este registro será fundamental para reconstruir liquidaciones ante inspecciones, reclamos o diferencias detectadas posteriormente.

---

# 17. Despliegue local y web

La aplicación deberá compartir el mismo código en las dos modalidades.

## 17.1. Aplicación local

El ejecutable generado mediante PyInstaller iniciará FastAPI en la propia computadora.

El flujo será:

```text
Usuario ejecuta Payroll.exe
             │
             ▼
Verificar configuración
             │
             ▼
Inicializar SQLite
             │
             ▼
Ejecutar migraciones necesarias
             │
             ▼
Iniciar FastAPI en 127.0.0.1
             │
             ▼
Abrir navegador predeterminado
             │
             ▼
Interfaz AdminLTE
```

La aplicación funcionará sin Docker y sin requerir que el usuario instale Python.

Los archivos estáticos de AdminLTE deberán estar incluidos en el ejecutable, evitando dependencias obligatorias de CDNs externos.

### Almacenamiento local

Los datos no deberán guardarse dentro del ejecutable ni en los directorios temporales de PyInstaller.

Se utilizará un directorio persistente del usuario, por ejemplo mediante `platformdirs`.

También deberán implementarse copias de seguridad y procedimientos de migración antes de actualizar la versión de la aplicación.

El servidor local deberá escuchar únicamente en `127.0.0.1`, con protección contra solicitudes no autorizadas incluso desde el navegador.

## 17.2. PyInstaller

Recomiendo utilizar inicialmente `--onedir`, porque simplifica la distribución de templates HTML, recursos estáticos y dependencias.

Posteriormente podrá evaluarse `--onefile`.

PyInstaller permite distribuir aplicaciones sin instalar Python, pero no es un compilador cruzado: los ejecutables Windows deben generarse en Windows y los de Linux en Linux. [GitHub](https://github.com/pyinstaller/pyinstaller?utm_source=chatgpt.com)

## 17.3. Despliegue web

Arquitectura inicial:

```text
           INTERNET
              │
              ▼
       Traefik / Nginx
              │
              ▼
       FastAPI Container
              │
        ┌─────┴─────┐
        ▼           ▼
   PostgreSQL     Workers
                    │
                    ▼
               Redis / Cola
```

Los servicios de base de datos y cola no deberán exponer puertos públicos.

Para un servidor pequeño puede comenzar utilizándose una sola instancia de FastAPI.

Los workers deberán poder ampliarse independientemente cuando aumenten las liquidaciones, exportaciones y análisis de convenios.

---

# 18. Compilación automática mediante GitHub Actions

La automatización de compilación debe formar parte del proyecto desde las primeras fases.

## 18.1. Flujo CI/CD

```text
Push / Pull Request
        │
        ▼
  Ruff + mypy
        │
        ▼
      pytest
        │
        ▼
  Tests de liquidación
        │
        ▼
  Tests de exportación
        │
        ▼
   ┌────┴──────────────┐
   ▼                   ▼
Windows Runner      Linux Runner
   │                   │
   ▼                   ▼
PyInstaller         PyInstaller
   │                   │
   ▼                   ▼
Payroll.exe         Payroll Linux
   │                   │
   └─────────┬─────────┘
             ▼
       GitHub Artifacts
             │
             ▼
      GitHub Releases
```

GitHub Actions permite utilizar matrices de ejecución para realizar compilaciones sobre diferentes sistemas operativos. [GitHub Docs](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax?utm_source=chatgpt.com)

## 18.2. Ejemplo de workflow

Una estructura inicial sería:

```yaml
name: Build Desktop

on:
  push:
    tags:
      - "v*"
  workflow_dispatch:

jobs:
  build:
    strategy:
      matrix:
        os:
          - windows-latest
          - ubuntu-22.04

    runs-on: ${{ matrix.os }}

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.13"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[desktop]"

      - name: Run tests
        run: |
          python -m pytest tests/

      - name: Build executable
        run: |
          pyinstaller desktop/payroll.spec --noconfirm

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: payroll-${{ matrix.os }}
          path: dist/
```

Es una base para el pipeline; presupone que `pyproject.toml` define el extra `desktop` y que existe un archivo `.spec` configurado.

El proceso completo de publicación deberá agregar empaquetado, hashes de integridad, firma cuando corresponda y creación de una release.

### Distribuciones previstas

| Plataforma | Artefacto |
|---|---|
| Windows x64 | ZIP o instalador con ejecutable |
| Linux x64 | Archivo comprimido con ejecutable |
| Docker | Imagen publicada en un registry |
| Código fuente | Paquete/versionado en Git |

Se deberán utilizar versiones fijadas de Python y dependencias para garantizar builds reproducibles.

En Linux, la compatibilidad del ejecutable deberá probarse contra las distribuciones objetivo.

---

# 19. Integración contable

Esta funcionalidad es especialmente importante para estudios contables.

Una liquidación aprobada deberá poder generar asientos según un plan de cuentas configurable.

## 19.1. Ejemplo ilustrativo

| Cuenta | Debe | Haber |
|---|---:|---:|
| Sueldos y jornales | 1.000.000 | |
| Cargas sociales | 250.000 | |
| Sueldos a pagar | | 800.000 |
| Retenciones y aportes a depositar | | 200.000 |
| Contribuciones a depositar | | 250.000 |
| **Total** | **1.250.000** | **1.250.000** |

La configuración deberá permitir asignar cuentas distintas por concepto, empresa, sector o centro de costos.

También deberá ser posible diferenciar el devengamiento del pago.

Los asientos podrán exportarse mediante Excel, CSV, JSON o enviarse a sistemas contables a través de la API.

---

# 20. Estrategia de pruebas

El principal riesgo del proyecto no será FastAPI, PostgreSQL o AdminLTE.

**El riesgo principal será la exactitud de los cálculos laborales y la correspondencia de los resultados con la normativa aplicable.**

Por ese motivo, las pruebas deberán ocupar una parte importante del desarrollo.

## 20.1. Pruebas del motor

Casos mínimos:

| Prueba | Objetivo |
|---|---|
| Sueldo mensual completo | Validar conceptos ordinarios |
| Ingreso durante el mes | Validar proporcionalidad |
| Jornada parcial | Validar reglas aplicables |
| Horas extras | Validar cantidades y recargos |
| Antigüedad | Validar fechas y porcentajes |
| Vacaciones | Validar períodos y bases |
| SAC | Validar acumulados y proporcionalidad |
| Retroactivos | Validar diferencias históricas |
| Licencias | Validar situaciones específicas |
| Liquidación final | Validar conceptos aplicables |
| Topes | Validar límites previsionales |
| Múltiples liquidaciones | Evitar duplicaciones |
| Cambio de categoría | Validar historiales |
| Cambio de convenio | Validar vigencia |
| Conceptos no remunerativos | Validar bases imponibles |

## 20.2. Golden tests

Recomiendo mantener un repositorio de liquidaciones reales previamente verificadas y anonimizadas.

Cada caso contendrá entradas, reglas aplicadas y resultados esperados.

El sistema deberá reproducir los resultados dentro de las tolerancias de redondeo establecidas.

## 20.3. Pruebas de exportación

Para Libro Sueldos Digital deberán existir pruebas byte a byte contra archivos de referencia.

Esto incluye codificación, formato numérico, longitudes, rellenos y caracteres de control.

También deberán existir pruebas de integración con los procedimientos oficiales, cuando sea posible.

## 20.4. Pruebas de IA

Se recomienda crear un conjunto de convenios y acuerdos interpretados previamente por profesionales.

Se medirá:

- Exactitud en la extracción de importes.
- Detección de fechas de vigencia.
- Identificación de categorías.
- Exactitud de fórmulas propuestas.
- Calidad de las referencias documentales.
- Detección de ambigüedades.
- Porcentaje de reglas que requieren corrección humana.

El objetivo no será únicamente obtener JSON válido, sino reglas correctas desde el punto de vista funcional y normativo.

---

# 21. Roadmap de desarrollo

Propongo dividir el desarrollo en siete fases.

Las duraciones son estimativas y dependen del tamaño del equipo y de la disponibilidad de especialistas en liquidación de sueldos.

| Fase | Objetivo | Duración estimada |
|---|---|---:|
| 0 | Análisis funcional y normativo | 2 semanas |
| 1 | Infraestructura y modelos | 3 semanas |
| 2 | Motor de liquidación | 5 semanas |
| 3 | Argentina y exportadores | 4 semanas |
| 4 | Inteligencia artificial | 4 semanas |
| 5 | Integraciones y distribución | 3 semanas |
| 6 | Validación integral y piloto | 4 semanas |
| **Total** | **Primera versión integral** | **25 semanas** |

## Fase 0. Definición funcional

**Duración: 2 semanas.**

Entregables:

- Alcance funcional del MVP.
- Definición del primer CCT.
- Casos de liquidación de referencia.
- Reglas normativas iniciales.
- Definición del DSL.
- Especificaciones de exportación.
- Modelo de datos preliminar.

No iniciaría el motor matemático antes de contar con liquidaciones de referencia verificadas.

## Fase 1. Infraestructura

**Duración: 3 semanas.**

Entregables:

- Proyecto FastAPI.
- Integración SQLAlchemy.
- Alembic.
- SQLite y PostgreSQL.
- Modelos de empresas y trabajadores.
- Autenticación.
- Frontend AdminLTE.
- Docker.
- Pipeline de tests y builds inicial.

Al finalizar deberá existir una aplicación funcional, aunque todavía no liquide sueldos.

## Fase 2. Motor de liquidación

**Duración: 5 semanas.**

Entregables:

- Motor DSL.
- Evaluador de fórmulas.
- Registro de conceptos.
- Dependencias.
- Parámetros versionados.
- Liquidación individual.
- Liquidación masiva.
- Historial de resultados.
- Simulaciones.
- Tests matemáticos y funcionales.

Esta fase deberá poder liquidar casos completos sin utilizar IA.

## Fase 3. Argentina

**Duración: 4 semanas.**

Entregables:

- Primer CCT configurado.
- Parámetros laborales y previsionales iniciales.
- Liquidaciones habituales.
- Recibos PDF.
- TXT de conceptos ARCA.
- TXT de liquidaciones ARCA.
- Validaciones.
- Reportes de control.

Al finalizar esta fase existirá un **MVP funcional para liquidar sueldos en Argentina dentro del alcance normativo y convencional implementado**.

## Fase 4. Inteligencia artificial

**Duración: 4 semanas.**

Entregables:

- Carga y procesamiento de convenios.
- Extracción de información estructurada.
- Generación de reglas DSL.
- Referencias normativas.
- Validaciones automáticas.
- Editor de propuestas.
- Aprobación humana.
- Comparación de versiones.

Esta fase incorporará el principal diferencial del producto.

## Fase 5. Integraciones y distribución

**Duración: 3 semanas.**

Entregables:

- API REST estabilizada.
- Servidor MCP.
- Importadores Excel/CSV.
- Exportación contable inicial.
- Ejecutables Windows y Linux.
- Docker Compose de producción.
- Compilación automática con GitHub Actions.
- Documentación de instalación.

## Fase 6. Piloto

**Duración: 4 semanas.**

Entregables:

- Pruebas con empresas reales.
- Comparación de liquidaciones históricas.
- Validación de archivos oficiales.
- Corrección de diferencias.
- Pruebas de restauración y migración.
- Pruebas de seguridad.
- Manuales de uso.
- Primera release estable.

---

# 22. Definición del MVP

Para evitar que el proyecto se vuelva excesivamente grande, establecería el siguiente alcance.

| Funcionalidad | MVP | Posterior |
|---|:---:|:---:|
| Multiempresa | ✅ | |
| Empleados y contratos | ✅ | |
| Importación Excel/CSV | ✅ | |
| Convenios configurables | ✅ | |
| Motor DSL | ✅ | |
| Fórmulas versionadas | ✅ | |
| Liquidación mensual | ✅ | |
| SAC y vacaciones | ✅ | |
| Liquidación final | Parcial | ✅ |
| Retroactivos | Básicos | Avanzados |
| Bases imponibles | ✅ | |
| Ganancias | Casos definidos | Cobertura ampliada |
| Recibos PDF | ✅ | |
| TXT conceptos LSD | ✅ | |
| TXT liquidaciones LSD | ✅ | |
| Validación de exportadores | ✅ | |
| IA para generar fórmulas | ✅ | |
| Análisis de nuevos acuerdos | Básico | Avanzado |
| API REST | ✅ | |
| MCP Server | | ✅ |
| PyInstaller | ✅ | |
| Docker | ✅ | |
| GitHub Actions | ✅ | |
| Contabilidad | Básica | Avanzada |
| Firma electrónica/digital | | ✅ |
| Portal del empleado | | ✅ |
| Nuevos países | | ✅ |

**Para la primera versión comercial, priorizaría la exactitud de los cálculos y la confiabilidad de los archivos oficiales por encima de la cantidad de convenios soportados.**

---

# 23. Recomendaciones para el mantenimiento del sistema

Hay un aspecto adicional que considero crítico: el mantenimiento normativo.

El sistema necesitará incorporar nuevas escalas salariales, parámetros fiscales, mínimos, topes, acuerdos y modificaciones legales.

Si todo esto depende de publicar nuevas versiones del software, el mantenimiento será costoso.

Por ello propongo separar:

**Actualizaciones del programa:** nuevas funcionalidades, correcciones y mejoras técnicas.

**Actualizaciones de contenido normativo:** escalas, parámetros, reglas aprobadas y especificaciones de salida.

Las actualizaciones normativas podrán distribuirse como paquetes versionados, firmados y verificables.

Esto permitirá que las aplicaciones locales actualicen reglas sin necesariamente reemplazar el ejecutable.

Además, cada instalación deberá poder consultar qué paquetes normativos tiene instalados y si están actualizados.

En escenarios sin conexión a Internet, los paquetes podrán importarse manualmente.

---

# 24. Criterios de aceptación de la primera versión

Consideraría que el sistema está preparado para una primera implementación profesional cuando cumpla estos requisitos:

| Área | Criterio |
|---|---|
| Liquidación | Reproduce los casos de referencia aprobados |
| Versionado | Permite reconstruir liquidaciones históricas |
| Convenios | Soporta al menos un CCT completo dentro del alcance definido |
| Fórmulas | Permite crear y modificar reglas sin cambiar código Python |
| IA | Genera propuestas estructuradas y fundamentadas |
| Seguridad IA | No ejecuta código arbitrario ni publica reglas automáticamente |
| ARCA | Genera archivos con el formato vigente validado |
| Recibos | Emite PDF conforme al alcance legal implementado |
| Auditoría | Conserva entradas, reglas, cálculos y aprobaciones |
| SQLite | Funciona correctamente en modo local |
| PostgreSQL | Funciona correctamente en modo servidor |
| Migraciones | Actualiza esquemas sin pérdida de datos |
| API | Expone operaciones documentadas mediante OpenAPI |
| Docker | Permite despliegue reproducible |
| PyInstaller | Genera ejecutables utilizables en Windows/Linux |
| GitHub Actions | Ejecuta tests y compila automáticamente |
| Recuperación | Restaura correctamente backups de prueba |

---

# 25. Decisiones arquitectónicas finales

Para este proyecto tomaría las siguientes decisiones desde el principio:

| Decisión | Recomendación |
|---|---|
| Arquitectura general | Monolito modular |
| Backend | FastAPI |
| ORM | SQLAlchemy 2.x |
| Migraciones | Alembic |
| Base predeterminada | SQLite |
| Base para servidores | PostgreSQL |
| Frontend | AdminLTE 4 + Jinja2 + HTMX |
| Motor de cálculos | Python + Decimal |
| Definición de fórmulas | DSL declarativo en JSON |
| Almacenamiento de reglas | SQLAlchemy |
| Versionado normativo | Por vigencia y revisión |
| Interpretación de convenios | LLM + RAG |
| Ejecución de liquidaciones | Determinística |
| Validación de fórmulas | Automática + revisión humana |
| Integración externa | REST + MCP |
| PDF | HTML/CSS + WeasyPrint |
| Exportaciones oficiales | Adaptadores versionados por jurisdicción |
| Almacenamiento documental | Filesystem / S3 compatible |
| Procesos extensos | Cola persistente |
| Versión local | PyInstaller |
| Versión servidor | Docker |
| Compilaciones | GitHub Actions |
| Tests | pytest + casos de referencia |

## Conclusión

La propuesta consiste en desarrollar una **plataforma de liquidación de sueldos basada en reglas normativas versionadas**, donde la inteligencia artificial permita reducir significativamente el trabajo de interpretar y parametrizar convenios colectivos.

El principal valor del proyecto no estará solamente en calcular sueldos, sino en poder:

1. Incorporar un nuevo convenio colectivo sin reprogramar el motor.
2. Interpretar sus disposiciones mediante IA.
3. Generar fórmulas y parámetros a partir de documentación normativa.
4. Validar y aprobar esas reglas.
5. Aplicarlas a liquidaciones individuales o masivas.
6. Reconstruir exactamente los resultados históricos.
7. Generar los archivos oficiales requeridos por cada jurisdicción.
8. Utilizar todas esas capacidades desde una aplicación local, web o mediante API.

**Mi recomendación es desarrollar primero un motor de liquidación autónomo, confiable y completamente independiente de la IA.** Una vez validado con casos reales y con los formatos oficiales de Argentina, incorporar la IA como un sistema de generación, actualización y revisión de reglas.

Este orden permitirá alcanzar un MVP utilizable antes de completar la automatización inteligente y facilitará la incorporación de nuevos convenios, jurisdicciones y clientes sin rediseñar la aplicación.