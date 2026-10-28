# Continuación de pendientes — 28 de octubre de 2026

Estado histórico del commit `bf78542`. La siguiente etapa se registra en
[Implementación de pendientes](PENDIENTES_IMPLEMENTADOS_2026-10-28.md).

## Resultado

El circuito SQL ahora permite crear una liquidación, revisar y confirmar
novedades CSV/XLSX, calcular, inspeccionar errores y trazas, reabrir, recalcular,
aprobar y descargar resultados/recibos desde la web. Empresas, empleados,
contratos, conceptos y fórmulas deben estar configurados previamente mediante
las APIs existentes. La demo conserva sus datos ilustrativos y no escribe
liquidaciones SQL.

Se utilizaron tres subagentes `gpt-6-luna:xhigh` para explorar el proceso,
el ERP y los pendientes, y tres `gpt-6.1-terra:xhigh` para implementar
novedades, interfaz y motor. La coordinación integró parámetros por alcance,
migraciones, guardas de aprobación, ZIP y validación conjunta. No se añadieron
dependencias ni se ejecutó el código decompilado.

## Referencias utilizadas

- PDF local: `/home/abp/Downloads/920015926-Liquidacion-de-Sueldos.pdf`,
  60 páginas físicas. P. 47: recibo histórico; pp. 50–55: conceptos y SAC
  proporcional. Se usa como material educativo y fixture de cálculo, no
  como catálogo de tasas vigentes.
- ERP local: `/media/abp/SSD/Proyectos Python/Scripts/nacional-decompiled`.
  `03-logic/modulos/sueldo/01b-liquidacion-novedades.md`: generación y
  recálculo, novedades por período y bloqueo por cierre.
  `06-decompiled/server/mod_sueldo/ns/nacional/sueldo/ReciboServiceImpl.java`,
  líneas 297 y 360: cierre y orden de conceptos;
  `formula/VariableReciboParser.java`, línea 2038: lectura de novedades.
  Se conservaron las fórmulas declarativas, dependencias y versiones del
  proyecto actual; no se portó el DSL ni la arquitectura del ERP.
- Se consultaron el [texto de la Ley 23.041](https://www.argentina.gob.ar/normativa/nacional/ley-23041-28165/texto)
  y el [texto actualizado de la LCT](https://www.argentina.gob.ar/normativa/nacional/25552/actualizacion).
  La base del SAC parte de la mayor remuneración mensual computable del
  semestre. Esta consulta no certifica encuadres, tasas o escenarios del sistema.

El PDF contiene discrepancias que las pruebas dejan explícitas: en p. 47,
46.440,31 remunerativos + 1.000 no remunerativos − 9.155,86 de descuentos
dan **38.284,45**, mientras el neto impreso es 37.284,45. En el ejemplo de
20.000 × 50 % × 141/181, HALF_UP a dos decimales da **7.790,06**, frente
a 7.790,05 impreso. No se alteró la aritmética para reproducir esas diferencias.

## Novedades y consistencia

`PayrollNovelty.company_id` identifica el empleador. La clave de importación
es empleado, empresa, período, código y origen. Si no se envía empresa,
solo se infiere cuando los contratos del mes identifican una única empresa.
Una empresa explícita también exige un contrato correspondiente al período.
La organización autenticada sigue restringiendo todos los accesos.

La migración asigna empresa a datos históricos únicamente cuando puede
determinarla sin ambigüedad. Los demás conservan NULL. En el cálculo, los
registros históricos se admiten solo con atribución inequívoca; los ambiguos
o duplicados producen ERROR de corrida y una revisión persistida, sin
reutilizar recibos anteriores ni devolver un error interno del servidor.
La reparación de datos históricos ambiguos requiere asignación administrativa
explícita; todavía no hay una pantalla para esa corrección.

Una novedad nueva invalida corridas calculadas, en revisión o con error de
esa empresa/mes: vuelve a DRAFT, elimina resultados y trazas, limpia hashes
y paquete de reglas y registra auditoría. Una repetición idempotente no
invalida. Si existe corrida aprobada/cerrada o en cálculo, se informa error
de fila y no se importa esa novedad. Los errores por fila conservan el contrato
de importación parcial; revisar siempre los conteos y mensajes del lote.

La creación de corridas y la importación comparten bloqueo de empresa; la
importación además bloquea corridas antes de comprobar estados. Las pruebas
son SQLite; no se afirma validación concurrente de PostgreSQL bajo carga.

## Parámetros y fórmulas especiales

Los parámetros admiten `agreement_code` y `category_code`. Vacío significa
global/todas las categorías; una categoría exige convenio. La resolución es
categoría del convenio → convenio → global, con vigencia inclusiva. Dos
parámetros aplicables superpuestos del mismo alcance producen error de
configuración, en lugar de elegir uno arbitrariamente. El importador de
paquetes incluye ambos campos en su identidad y validación de solapamientos.
No se infiere alcance del nombre del código: los catálogos históricos sin
estos campos conservan su alcance global y deben clasificarse explícitamente.

El snapshot guarda identificadores, valores, alcances, vigencias y versiones;
los parámetros efectivos de cada empleado participan en su entrada de cálculo.

Las fórmulas de descuentos y contribuciones para corridas especiales deben
tener la condición versionada exacta:

```json
{"field": "run_type", "operator": "eq", "value": "SAC"}
```

También se admiten `VACATIONS` y `FINAL`. Se respetan alcance por convenio/
categoría, aprobación y vigencia. Las reglas sin tipo conservan su uso mensual;
las especiales no vuelven a ejecutar el sueldo básico mensual.

Para las expresiones están disponibles los parámetros
`settlement_remunerative`, `settlement_non_remunerative`, `settlement_gross`
y `settlement_<CODIGO_COMPONENTE>`, además de los parámetros normativos
seleccionados. Se reutiliza el calculador existente con su redondeo y traza.
No se incorporaron tasas legales predeterminadas. Una regla cero explícita
puede representar una naturaleza sin importe, si esa configuración fue revisada.

Bruto, descuentos, contribuciones, neto y costo empleador se guardan y
serializan con coherencia. Faltar reglas de cualquiera de las dos naturalezas
deja advertencia de incompletitud y **bloquea aprobación** en la API y la web.
Las corridas vacías quedan ERROR y tampoco se aprueban.

## SAC y liquidación final

El SAC persistente usa días calendario inclusivos trabajados dentro del
semestre y su duración real, conservando el prorrateo exacto con Decimal.
La base requiere historia mensual completa y sin duplicaciones para los
meses esperados, o una novedad `SAC_BASE` de naturaleza `AUXILIARY` y un
importe positivo explícito. Ya no se reemplaza silenciosamente el historial
por el salario contractual. La traza expone días, historia, faltantes y base.
No se infieren licencias sin goce ni otras exclusiones de devengamiento: deben
completarse esos escenarios antes de afirmar cobertura general.

FINAL muestra bajas sin contrato cuando no existe atribución inequívoca o
hay vínculo con la empresa de la corrida; no presenta una corrida sin
personas como exitosa. Conserva un cálculo parcial: faltan causa de egreso,
base indemnizatoria adecuada, fracciones de antigüedad y escenarios específicos.
Una advertencia de alcance incompleto impide aprobarla, aun si hay resultados
para revisar. El bloqueo evita presentar el cálculo parcial como definitivo.

## Interfaz y operación

La confirmación de importación exige volver a seleccionar el mismo archivo;
la firma verifica contenido SHA-256, extensión, usuario y corrida, con
vencimiento. No se guarda el archivo salarial en una sesión del servidor.
La carga web exige que las filas correspondan al mes de la corrida.
CSRF, roles y aislamiento organizacional se verifican en cada escritura.

`CALCULATION_REVIEW` conserva resumen, errores y advertencias después de la
redirección; el detalle permite desplegar trazas por empleado y fórmula.
El ZIP respeta todos los filtros del listado, incluida búsqueda/estado,
en todas las páginas. El archivo completo sigue generándose en memoria.

Para una base existente es necesario aplicar, antes de iniciar esta versión:

```sh
.venv/bin/python -m alembic upgrade head
```

La única cabeza es `h9a1b2c3d4e5`, posterior a
`g8a1b2c3d4e5` (empresa de novedades). Se probaron upgrades con datos,
backfill inequívoco, preservación de ambigüedades y downgrade de parámetros.
Los downgrades no descartan registros incompatibles con la unicidad anterior.
Las migraciones se ejecutaron en bases temporales; no se migró la base de trabajo.

## Validación y pendientes

El E2E automatizado SQL recorre login/CSRF, creación, preview, confirmación,
cálculo, trazas, reapertura, recálculo, aprobación y descargas. Incluye rechazos
por rol, CSRF, organización, período y archivo cambiado. Chrome recorrió
creación/importación/cálculo/reapertura/recálculo/aprobación en base temporal,
con descargas CSV y F.931 HTTP 200, sin errores JavaScript ni desbordamiento
de página a 390 px. Se revisaron capturas móvil y escritorio.

Pendientes principales: completar FINAL por causa, gestionar ajustes o
anulación de aprobadas, dar interfaz a la reparación de novedades históricas
ambiguas y a la configuración de conceptos/fórmulas/parámetros, ampliar
escenarios de devengamiento de SAC/vacaciones, probar PostgreSQL concurrente
y validar exportaciones oficiales. LSD no fue presentado ante ARCA y F.931
sigue siendo una planilla interna. No se certifica aptitud para producción.

Validación final: **752 pruebas pasaron en 101,96 segundos**, cobertura
**88,97 %** (mínimo 80 %), Ruff sin hallazgos, Mypy sin errores en 100
archivos y `git diff --check` limpio. Solo se observa la advertencia de
deprecación de Starlette TestClient/httpx.
