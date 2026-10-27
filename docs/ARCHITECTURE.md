# Arquitectura

Este documento describe la arquitectura implementada en el repositorio y separa
lo que ya funciona de lo que todavía es una brecha del MVP. La referencia de
producto es `plan.md`; cuando el código no alcanza ese alcance, se indica.

## Principio central

La IA propone, el motor determinista calcula y una persona aprueba. Ningún
modelo de lenguaje ejecuta fórmulas, publica reglas ni modifica una liquidación
por sí solo.

El sistema se apoya en cuatro capas:

| Capa | Responsabilidad | Código principal |
|---|---|---|
| Entrada y presentación | API REST, UI Jinja2, importación de archivos | `app/api`, `app/web`, `app/importers` |
| IA supervisada | Extraer texto, interpretar documentos y proponer reglas | `app/ai` |
| Normativa | Parámetros, escalas, vigencias y reglas de Argentina | `app/core/normative`, `app/jurisdictions/argentina` |
| Cálculo y salidas | Evaluar el DSL, consolidar resultados y generar documentos | `app/core/payroll_engine`, `app/exporters`, `app/services` |

## Flujo principal

```text
Documento PDF/TXT/MD/HTML
        |
        v
Extraccion de texto y hash SHA-256
(app/ai/documents/extraction.py)
        |
        v
Analisis con proveedor LLM o MockProvider
(app/ai/analysis.py)
        |
        v
AgreementAnalysis con conceptos, parametros y formulas en estado draft
        |
        v
Validacion determinista
(esquema, fuente, DSL, dependencias, fechas, tests sugeridos)
(app/ai/validation.py)
        |
        v
Revision humana
(validate_proposal -> approved_by)
        |
        v
[BRECHA] Publicacion de la propuesta como formula versionada
hoy requiere crear la formula por la API y aprobarla por separado
        |
        v
FormulaDefinition + FormulaVersion
(DRAFT -> VALIDATED -> APPROVED, con vigencia)
        |
        v
calculate_payroll: DSL interpretado con Decimal
(app/core/payroll_engine)
        |
        v
PayrollResult + PayrollItem + PayrollTrace
(servicio de calculo persistente)
        |
        +--> Recibo HTML/PDF/ZIP
        |    (app/exporters/pdf)
        |
        +--> TXT de Libro de Sueldos Digital
             (app/exporters/txt)
```

La aprobación de una propuesta de IA y la aprobación de una fórmula son dos
actos distintos. `app/ai` devuelve un registro de revisión y nunca escribe en
`FormulaVersion`. La publicación real sigue siendo una operación humana a
través de la API de fórmulas.

## Componentes

### 1. Extracción de documentos

`extract_text` acepta `.txt`, `.md`, `.html`, `.htm` y `.pdf`. Normaliza saltos
de línea, calcula el hash del texto extraído y conserva metadatos como
identificador, versión, título, jurisdicción y páginas del PDF.

Límites actuales:

- no hay OCR, por lo que un PDF escaneado sin capa de texto no se puede usar;
- no se procesan archivos DOCX;
- el texto se considera contenido no confiable y se envía con una advertencia
  explícita al modelo;
- el hash cubre el texto extraído, no el archivo binario original.

### 2. Análisis con IA

`analyze_agreement` recibe texto, un proveedor y metadatos. El proveedor debe
devolver un único objeto JSON. La respuesta se valida con Pydantic y se
reconstruyen los campos que controla el sistema:

- `document` y `content_hash` se toman del documento real;
- las fuentes propuestas se comparan contra el documento y la versión;
- cualquier intento del modelo de marcar una fórmula como aprobada se revierte
  a `draft`;
- se eliminan aprobaciones, rechazos y reportes de validación inventados;
- se agregan advertencias heurísticas de posible inyección de instrucciones.

El proveedor `OpenAICompatibleProvider` permite usar una API compatible con
`/chat/completions`. La API HTTP montada en `/api/v1/ai` usa `MockProvider` por
defecto para funcionar sin red. Para usar un proveedor real hay que sobrescribir
la dependencia `get_ai_provider` en código; no hay configuración de proveedor
por variable de entorno en esa ruta.

### 3. Validación

La validación de propuestas es determinista y no ejecuta la fórmula. Revisa:

- esquema y campos obligatorios;
- hash y referencia de la fuente;
- operadores y estructura del DSL;
- variables, parámetros y conceptos referenciados;
- dependencias y ciclos;
- rango de vigencia;
- tests sugeridos, que quedan registrados para revisión humana.

Si el motor expone su validador estático, se usa como control adicional. El
reporte resultante indica errores, advertencias, controles ejecutados y
limitaciones. Un reporte válido no equivale a una aprobación.

### 4. Aprobación y publicación

`validate_proposal` solo pasa de `draft` a `validated` cuando no hay errores.
`approve_proposal` exige:

- un identificador de persona aprobadora;
- estado `validated`;
- un reporte de validación válido;
- revalidación estructural en el momento de aprobar.

La API `POST /api/v1/ai/proposals/approve` exige rol `admin` o `editor` y usa
la identidad del usuario autenticado. El `approved_by` que venga en el cuerpo
se sobrescribe con el correo de la sesión, o con `user:<id>` si no hay correo.
El endpoint legacy `/ai/proposals/approve` devuelve un registro en memoria; el
flujo persistido usa `/ai/proposals/{id}/approve` y guarda el estado en
`ai_proposals`.

La propuesta aprobada se puede persistir en `ai_proposals` y publicar
manualmente con `POST /api/v1/ai/proposals/{id}/publish`. Esa publicación crea
una `FormulaVersion` en estado `DRAFT`; después hay que validarla y aprobarla
por el flujo de fórmulas. `POST /api/v1/formulas/{id}/versions` permite crear
versiones nuevas sin sobrescribir las anteriores.

### 5. Motor de cálculo

`app/core/payroll_engine` es la parte determinista:

- `formula_engine.py` interpreta árboles JSON del DSL, sin `eval` ni ejecución
  de Python arbitrario;
- `dependency_resolver.py` ordena conceptos y detecta ciclos;
- `calculator.py` normaliza empleado, novedades y parámetros, selecciona las
  definiciones vigentes y consolida el resultado;
- `tax_bases.py`, `rounding.py` y `concepts.py` aplican bases, redondeo y
  clasificación por naturaleza;
- todos los importes se operan con `Decimal`.

El motor no contiene alícuotas, topes ni fórmulas legales. Esos valores llegan
como parámetros y definiciones versionadas. `calculate_payroll` calcula un
empleado; el servicio `app/services/payroll_calculation.py` recorre una corrida,
persiste resultados y trazas y marca la corrida como `CALCULATED` o `ERROR`.

La selección del servicio usa el `period_end` de la corrida, contratos activos
vigentes, una única escala por categoría y fórmulas en estado `APPROVED`
(solo aprobadas; `VALIDATED` no liquida). Si un empleado no tiene contrato, categoría, escala o conceptos
suficientes, se registra el error y se continúa con el resto.

### 6. Resultados y salidas

Cada resultado conserva:

- conceptos calculados, naturaleza, cantidad, valor unitario e importe;
- totales remunerativos, no remunerativos, deducciones, contribuciones, bruto,
  neto y costo del empleador;
- una traza textual del cálculo;
- hashes de entradas y resultados de la corrida.

Los recibos se renderizan a HTML, PDF y ZIP con Jinja2 y WeasyPrint. El contexto
se valida y se arma con una lista blanca de campos; los datos personales se
escapan. El PDF no acredita por sí solo firma, entrega o conservación
electrónica.

El exportador LSD genera TXT de ancho fijo en Latin-1 para liquidaciones y
conceptos, con validaciones de estructura. Es un MVP técnico y no cuenta con
aceptación de ARCA. Ver `docs/NORMATIVE_DATA.md` para los límites del layout y
los datos de demostración.

### 7. Importadores

`app/importers` lee CSV y XLSX, normaliza encabezados y valida filas de
empleados y novedades. Devuelve un preview con errores y duplicados, pero no
persiste nada y no está conectado a la API ni a la UI. Es una biblioteca pura,
no un proceso de importación operativo.

## Versionado y reproducibilidad

Las vigencias son inclusivas: `[valid_from, valid_to]`. Un período se compara
con la fecha de devengamiento, no con la fecha en que se cargó el dato.

- Los parámetros usan `ParameterVersion`, con estados `demo`, `draft`,
  `approved` y `obsolete`.
- Las escalas del proveedor demo usan `SalaryScale`, con vigencia, fuente,
  versión y marca de demostración. La tabla `salary_scales` conserva categoría,
  vigencia, importe y documento fuente.
- Las fórmulas usan `FormulaVersion`, con estado, vigencia y aprobación.
- Las corridas guardan `inputs_hash` y `results_hash`, y la traza incluye las
  versiones de fórmulas usadas.

El esquema de base de datos tiene campos para documento fuente, checksum,
publicación y registro. Sin embargo, no hay todavía un snapshot normativo
completo e inmutable por corrida ni un paquete de reglas aprobado. La promesa de
reproducibilidad histórica es parcial: depende de conservar las versiones y de
que no se reescriban los datos fuente.

## Límites de seguridad

Controles implementados:

- el documento se trata como contenido no confiable;
- el modelo no puede fijar estado de aprobación, hash ni identidad;
- el DSL es una lista blanca de operadores, sin ejecución de código;
- la validación y la aprobación son deterministas y revalidan;
- la API de negocio usa cookie firmada, contraseña con PBKDF2 y roles
  `admin`, `editor` y `viewer`;
- la UI web reutiliza esa cookie y `verify_password`. En modo demo valida el
  admin configurado; en modo SQL consulta la tabla `users`. Las rutas de negocio
  redirigen a `/login?next=...` y las peticiones HTMX reciben `401` con
  `HX-Redirect`;
- los formularios POST de la UI validan un token CSRF firmado con doble submit
  (cookie `payroll_csrf` + campo oculto); `viewer` no puede cambiar estados;
- `/login`, `/salud` y `/static/*` son públicos;
- las rutas de cálculo, edición y aprobación exigen rol;
- los recibos escapan datos y no imprimen claves desconocidas;
- los archivos de exportación no se cachean y se sirven como descarga.

Límites actuales:

- con `PAYROLL_WEB_DATA_SOURCE=sql` la UI filtra por la organización del
  usuario autenticado; sigue siendo una proyección de solo lectura;
- hay rate limiting de login en memoria, cambio de contraseña e invalidación de
  sesiones por `session_version`; faltan MFA, recuperación y un limitador
  compartido entre procesos;
- los valores por defecto de `PAYROLL_SECRET_KEY` y del admin demo son
  inseguros y deben cambiarse;
- las propuestas de IA se persisten en `ai_proposals`; la aprobación usa la
  identidad de la sesión y la publicación manual crea fórmulas `DRAFT`;
- `AuditLog` existe como modelo, pero las operaciones CRUD no lo completan de
  forma automática;
- no hay trabajos en segundo plano ni cola persistente en uso, aunque existen
  los modelos `BackgroundJob`;
- el exportador LSD no está validado contra ARCA y el recibo no resuelve por sí
  solo los requisitos de firma o entrega.

## Persistencia y auditoría

La persistencia usa SQLAlchemy 2.x y una migración inicial de Alembic. SQLite es
el perfil local y PostgreSQL está previsto para servidor. El archivo de
SQLite se configura con claves foráneas, WAL y `busy_timeout`.

Entidades principales:

- organización, usuarios y roles;
- empresas, establecimientos, empleados y contratos;
- convenios, categorías, escalas y conceptos;
- parámetros, documentos normativos y conjuntos de reglas;
- definiciones y versiones de fórmulas;
- corridas, resultados, conceptos liquidados, trazas y aprobaciones;
- registro de auditoría y trabajos en segundo plano.

Qué se escribe hoy:

- la API persiste empresas, empleados, convenios, conceptos y fórmulas;
- la aprobación de una fórmula queda en `FormulaVersion`;
- el cálculo persistente escribe `PayrollResult`, `PayrollItem` y
  `PayrollTrace`, y actualiza hashes y estado de la corrida;
- la aprobación de una liquidación escribe `PayrollApproval`;
- `AuditLog` no se completa automáticamente;
- las propuestas de IA y sus aprobaciones se guardan en `ai_proposals`; el
  endpoint legacy `/ai/proposals/approve` sigue devolviendo un objeto en
  memoria.

La UI web exige autenticación (`PAYROLL_WEB_AUTH_ENABLED=true` por defecto) y
protege los POST con CSRF. Por defecto lee de `DemoDataStore`, un store en
memoria que permite mostrar el producto sin base; en ese modo el login valida
las credenciales de administrador configuradas. Si se configura
`PAYROLL_WEB_DATA_SOURCE=sql`, lee de `SqlAlchemyDataSource`, una proyección de
solo lectura sobre las tablas, autentica contra la tabla `users` y filtra
empresas, empleados, recibos y propuestas por la organización del usuario. En
ambos casos la UI es una capa de presentación, no una fuente de verdad para
liquidar.

## Brechas principales del MVP

1. La publicación de IA crea fórmulas `DRAFT`; falta un flujo de UI para
   revisarlas y aprobarlas.
2. El cálculo elige fórmulas por organización y fecha, pero todavía no por
   convenio, categoría o `ruleset_id`. Falta ese filtro para multi-CCT estricto.
3. SAC, vacaciones y liquidación final tienen API de simulación, pero no se
   eligen automáticamente desde el tipo de corrida.
4. Las novedades importadas se guardan como remunerativas y el período es
   `AAAAMM`; no cubren quincenas ni naturalezas no remunerativas.
5. La validación contra ARCA sigue pendiente.
6. No hay auditoría automática de cambios ni trabajos persistentes.
7. Docker y PyInstaller tienen configuración inicial, pero no builds
   verificados en este repositorio.
