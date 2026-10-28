# Implementación de pendientes — 28 de octubre de 2026

Continuación del commit `bf78542`, con tres subagentes `gpt-6.1-terra:xhigh`
y coordinación de integración. Se mantuvo Ponytail y no se añadieron
dependencias de aplicación.

## Alcance entregado

| Pendiente | Implementación | Límite explícito |
|---|---|---|
| FINAL por causa | Insumos por corrida/empleado, renuncia y despido sin causa; sueldo pendiente, SAC, vacaciones y componentes indemnizatorios que correspondan. Bases, topes, preaviso y días se validan y trazan. | Otros regímenes, causas y rubros adicionales no se presumen cubiertos. [Contrato y fuentes](LIQUIDACIONES_ESPECIALES.md). |
| Corrección de aprobadas | Anulación interna auditada sin borrar resultados; reemplazo completo DRAFT vinculado, idempotente. Los recibos y exportaciones de anuladas quedan bloqueados. | No es una rectificativa fiscal ni una reversión automática de importes presentados a ARCA. |
| Reparación de novedades | Pantalla admin para asignar empresa a registros históricos NULL con motivo, contrato del mes y controles de organización, colisión y estados. Invalida cálculos afectados. | Una corrida aprobada/cerrada o en cálculo que pueda haber usado el dato bloquea la reparación. |
| Configuración web | Alta de conceptos; fórmulas en borrador, versiones, condiciones, dependencias, alcance, redondeo, validación y aprobación; parámetros propios con vigencia, auditoría y aislamiento organizacional. | El editor avanzado de fórmulas usa JSON DSL. El catálogo global es de solo lectura; un alcance ya usado por versiones aprobadas no se modifica. |
| SAC y vacaciones | Días sin devengamiento SAC explícitos y base de vacaciones revisada que incluye variables/accesorios; formularios con insumos persistidos. | Las licencias y promedios aplicables se revisan expresamente; no se inventa la información ausente. |
| PostgreSQL | Cinco pruebas reales de migración, ciclo y bloqueos; job CI dedicado. Benchmark de 1.000 empleados. | Entorno local PG16, no prueba de capacidad de producción. [Evidencia e instrucciones](POSTGRES_VALIDATION.md). |
| Salidas oficiales | Cinco fuentes verificadas por SHA-256; siete salidas sintéticas coincidentes con las planillas oficiales recalculadas; fixtures y verificador reproducible. | No se accedió al portal con clave fiscal ni se presentó una liquidación. F.931 sigue siendo control interno. [Validación local](VALIDACION_ARCA.md). |

## Uso desde la interfaz SQL

1. En **Conceptos y fórmulas**, configurar conceptos, versiones aprobadas y
   parámetros propios. Los parámetros globales se consultan, no se editan.
2. Crear una liquidación y cargar sus novedades revisando y confirmando el
   archivo. Las bases especiales se completan en **Preparación y correcciones**.
3. Guardar los insumos de cada empleado, calcular, revisar trazas y aprobar.
   Falta de información, reglas o causas no soportadas bloquea el cálculo o
   su aprobación. Los campos vacíos no equivalen a cero.
4. Para corregir una aprobada, entrar a **Preparación y correcciones** y
   anular internamente o crear un reemplazo completo con código y motivo.
   El original queda consultable como historial.
5. **Reparar novedades** permite atribuir empresa a los registros históricos
   pendientes. No modifica recibos ya aprobados silenciosamente.

La [guía oficial 27 de ARCA](https://www.arca.gob.ar/LibrodeSueldosDigital/documentos/nuevos/G27-Ajuste-de-liq-aceptadas.pdf)
describe ajustes que complementan liquidaciones aceptadas; el reemplazo
interno implementado aquí tiene una semántica distinta. Una corrección fiscal
requiere el procedimiento oficial pertinente.

## Datos, integridad y migraciones

- `i1a2b3c4d5e6`: insumos tipados persistidos por corrida y empleado.
- `j1a2b3c4d5e6`: anulación conservando resultados y vínculo a reemplazo.
- `k1a2b3c4d5e6`: parámetros pertenecientes a una organización, manteniendo
  el catálogo global. La precedencia organizacional opera dentro del mismo
  alcance de convenio/categoría.
- Los snapshots ahora versionan por corrida; evita colisiones de secuencia
  cuando dos corridas diferentes se calculan simultáneamente.

La base local `data/payroll.db` se migró de `f7a1b2c3d4e5` a
`k1a2b3c4d5e6`. Antes se creó un backup consistente con la API de SQLite:
`backups/payroll-before-pending-20261028T195220Z.db` (archivo local ignorado
por Git). Tras migrar, `PRAGMA integrity_check` devolvió `ok` y
`PRAGMA foreign_key_check` no encontró problemas. No se ejecutó el seed sobre
la base local ni se calcularon nuevas liquidaciones en ella.

## Evidencia de pruebas

- Prueba SQL integrada por formularios: insumos FINAL de renuncia, cálculo,
  aprobación, bloqueo de cambios posteriores, reemplazo y reparación histórica.
- Configuración por formularios: concepto, fórmula, validación, aprobación,
  parámetro organizacional, cálculo del importe configurado, cierre de vigencia,
  aislamiento de otra organización, roles y CSRF.
- PostgreSQL: migración con resultados existentes, ciclo de nómina, reparación,
  rechazo de cálculo con estado desactualizado, serialización de importación
  frente a aprobación y snapshots de corridas paralelas.
- Chrome: ocho navegaciones en escritorio y móvil a configuración, reparación
  y operaciones; todas HTTP 200, sin errores JavaScript ni desbordamiento de
  página. Guardado real de días excluidos SAC y creación de reemplazo interno
  mediante formularios en base temporal; capturas revisadas.
- Benchmark: 1.000 empleados, tres conceptos y 3.000 ítems; tres iteraciones
  de cálculo y commit, mediana **2,137026 segundos**, hashes estables.
- Planillas oficiales: coincidencia carácter por carácter para registros
  01–06 y conceptos. Se documentó la anomalía de la fórmula de período de
  ajuste 03 en LibreOffice sin reproducirla en el exportador.

Suite conjunta final con PostgreSQL habilitado: **768 pruebas pasaron en
106,53 segundos**, sin omisiones, con **89,14 %** de cobertura (mínimo 80 %).
Ruff sin hallazgos, Mypy sin errores en 108 archivos y `git diff --check`
limpio. La única advertencia es la deprecación de Starlette TestClient/httpx.

## Qué sigue requiriendo intervención externa o ampliación

- Aceptación real de un archivo por el portal ARCA, con su validación fiscal
  y encuadre de una liquidación real. La evidencia local no sustituye ese paso.
- Regímenes especiales, otras causas de extinción, indemnizaciones agravadas,
  intereses o conceptos adicionales fuera de los dos escenarios soportados.
- Ajustes fiscales complementarios de liquidaciones ya aceptadas y su eventual
  presentación. El sistema registra correcciones internas, no hace esa gestión.
- Operación productiva: infraestructura, carga representativa y revisión de
  parámetros/configuraciones concretas del empleador.
