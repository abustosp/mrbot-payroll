# Datos normativos

Este documento describe cómo se representan hoy los parámetros y las escalas
normativas, por qué los valores incluidos son solo de demostración y qué falta
para reemplazarlos por un paquete aprobado y validado contra ARCA.

## Advertencia

El repositorio **no contiene datos normativos aprobados**. Los parámetros, las
escalas del CCT 130/75 y las tablas de Ganancias que se usan en tests y en la
demo son ilustrativos. No deben usarse para liquidaciones reales, presentaciones
ante ARCA ni decisiones laborales.

Tampoco deben interpretarse como asesoramiento legal. La fuente aplicable, la
vigencia y el tratamiento de cada concepto deben verificarse con la normativa
oficial y con un profesional responsable antes de operar.

## Qué existe hoy

La implementación actual se concentra en
`app/jurisdictions/argentina/provider.py` y en los helpers de
`app/core/normative/parameters.py`.

| Elemento | Dónde vive | Estado |
|---|---|---|
| Parámetros de aportes, contribuciones y CCT | `provider.py`, función `_demo_parameters` | Demo, fuente `demo-2026` |
| Escalas salariales CCT 130/75 | `provider.py`, `ARGENTINA_CCT_130_75_SCALES` | Demo, `illustrative=True` |
| Categorías CCT 130/75 | `provider.py`, `ARGENTINA_CCT_130_75_CATEGORIES` | Demo acotada a cuatro categorías |
| Reglas CCT de ejemplo | `provider.py`, `ARGENTINA_CCT_130_75_RULES` | Demo |
| Tramos de Ganancias | `provider.py`, `_demo_income_tax_brackets` | Demo, no representan alícuotas legales |
| Versiones de parámetros | `ParameterVersion` | Implementado |
| Selección por fecha | `select_parameter`, `select_parameters` | Implementado, con vigencias inclusivas |
| Detección de superposiciones | `find_overlaps`, `validate_no_overlaps` | Implementado |
| Persistencia de documentos y parámetros | `NormativeDocument`, `NormativeParameter`, `SalaryScale` | Modelos y migración inicial |
| Carga de un paquete aprobado | No existe | Pendiente |

La vigencia técnica de la demo es del 1 de enero al 31 de diciembre de 2026.
Es una decisión del código de ejemplo, no una afirmación sobre la vigencia
legal de ningún acuerdo.

El proveedor declara cuatro categorías, pero el seed solo carga `ADMIN_A` y
`ADMIN_B`. No hay sincronización automática entre los datos del proveedor y la
base: el flujo persistente usa las categorías y escalas que estén cargadas.

Los valores concretos se pueden inspeccionar en el módulo. No se repiten en
esta guía para evitar que una cifra de demostración se confunda con una
alícuota o un salario vigente.

## Versionado por vigencia

Cada versión de un parámetro debe conservar, como mínimo:

- código;
- valor en `Decimal`;
- fecha de inicio y fecha de fin, ambas inclusivas;
- fecha de publicación, si se conoce;
- fuente o documento de respaldo;
- número de versión;
- estado.

Los estados previstos por el código son `demo`, `draft`, `approved` y
`obsolete`. Un valor `demo` nunca debe promoverse a producción sin revisión.
La selección por período usa `[valid_from, valid_to]`: si `valid_to` es `None`,
la versión queda abierta. Los helpers `select_parameter` y `select_parameters`
rechazan versiones del mismo código cuyas vigencias se superpongan.

El servicio de cálculo persistente también selecciona parámetros por vigencia,
pero todavía no llama a ese validador de superposiciones: la carga ordenada del
paquete sigue siendo responsabilidad del importador y de la revisión previa.
El modelo `NormativeParameter` guarda vigencia, versión y documento fuente, pero
no una columna de estado; el estado `demo` vive en la estructura
`ParameterVersion`. El importador aprobado deberá definir cómo persiste y
audita ese estado.

Las escalas salariales siguen la misma idea. En el proveedor demo, cada escala
tiene categoría, importe mensual, vigencia, fuente, versión, estado e indicador
`illustrative`. El modelo SQLAlchemy conserva categoría, vigencia, importe,
adicional y documento fuente. Una categoría no puede tener dos escalas
superpuestas para el mismo período.

Las fórmulas también se versionan. `FormulaDefinition` identifica el concepto y
`FormulaVersion` conserva la expresión DSL, la vigencia y el estado
`DRAFT`, `VALIDATED`, `APPROVED` u `OBSOLETE`. La aprobación registra usuario y
fecha. Una liquidación debe seleccionar las versiones vigentes al período y no
las últimas cargadas.

Para que una liquidación histórica sea reproducible no basta con guardar el
resultado. También deben conservarse las versiones de fórmulas, parámetros,
escalas y documentos que se usaron. Los modelos incluyen referencias y campos
de hash, pero todavía falta cerrar el snapshot completo del conjunto de reglas
aplicado a cada corrida.

## Cómo reemplazar la demo por datos aprobados

El repositorio no tiene todavía un importador de paquetes normativos ni un
comando de actualización. El procedimiento recomendado es:

1. Obtener el documento oficial y registrar título, tipo, origen, fecha de
   publicación, ruta o URL y checksum.
2. Extraer los valores y las fechas sin completar datos faltantes por
   inferencia. Si una regla es ambigua, debe quedar pendiente.
3. Armar un paquete candidato separado de la demo, con una fuente identificable
   por cada valor.
4. Validar que no haya vigencias superpuestas, huecos no justificados,
   categorías sin escala o referencias a parámetros inexistentes.
5. Validar los rangos numéricos: porcentajes como fracción entre 0 y 1,
   importes no negativos, tramos contiguos y un único tramo final abierto
   cuando corresponda.
6. Agregar casos de prueba con ejemplos del documento y resultados revisados
   por un profesional. Los casos deben cubrir los extremos de cada vigencia.
7. Revisar y aprobar el paquete con un responsable identificado. La aprobación
   técnica del software no reemplaza la revisión profesional.
8. Cargar el paquete en una transacción, conservando las versiones anteriores y
   el documento fuente. No sobrescribir valores históricos.
9. Recalcular una muestra de liquidaciones y comparar contra los resultados
   esperados antes de habilitar el paquete.
10. Respaldar la base, desplegar y conservar el paquete anterior para poder
    volver atrás.

Mientras no exista un cargador, reemplazar los valores de `provider.py` es una
modificación de código. Ese cambio debe pasar por revisión, tests y aprobación
igual que cualquier otra regla, y no debe hacerse directamente en producción.

## Qué falta validar contra ARCA

El exportador `app/exporters/txt/lsd.py` genera archivos de ancho fijo con
codificación Latin-1 de un byte y valida estructura, fechas, CUIT y CUIL,
importes, caracteres ASCII, orden de registros y coherencia de trabajadores.
Eso no demuestra que ARCA acepte el archivo.

Falta contrastar y aprobar, como mínimo:

- la versión oficial del diseño de interfaz aplicable;
- la posición y el significado de cada campo en los registros 01 a 06;
- el layout completo de los registros 05, 06 y del archivo de conceptos, que
  hoy usan campos de reserva o estructuras de muestra;
- la correspondencia entre códigos internos y códigos de concepto de ARCA;
- los indicadores de aportes, contribuciones y bases;
- el tratamiento de SAC, vacaciones, retroactivos y ajustes;
- la codificación exacta y el fin de línea exigidos;
- la validación en un entorno autorizado, con datos de prueba y evidencia de
  aceptación.

El archivo de Libro de Sueldos Digital es un borrador técnico. No se debe
afirmar que es compatible con ARCA ni usarlo para una presentación real hasta
completar esa validación. La declaración jurada F.931 y la presentación oficial
no están implementadas.

Los recibos PDF se generan con una plantilla y una leyenda de demostración. La
emisión del archivo no acredita por sí sola firma, entrega o conservación
electrónica, ni cumple automáticamente los requisitos legales aplicables.

## Controles que deben mantenerse

- Ninguna regla nueva se publica sin revisión humana y aprobación registrada.
- Ningún valor se toma de un modelo de IA sin documento fuente, hash y
  validación determinista.
- Las vigencias se comparan siempre contra el período devengado, no contra la
  fecha de carga.
- Las versiones anteriores no se eliminan.
- Los cambios de parámetros, escalas, fórmulas y documentos quedan auditados.
- Los respaldos se prueban antes de actualizar datos normativos.
- Los datos demo se identifican como tales en la interfaz, los tests y la
  documentación.

## Checklist antes de una liquidación real

- [ ] El paquete normativo tiene fuente, versión y aprobación profesional.
- [ ] Las vigencias cubren todo el período sin superposiciones.
- [ ] Las escalas de todas las categorías usadas están cargadas.
- [ ] Las fórmulas están validadas y aprobadas para el período.
- [ ] Los casos de referencia dan el resultado esperado.
- [ ] El exportador fue validado contra la especificación oficial aplicable.
- [ ] Un usuario autorizado revisó y aprobó la liquidación.
- [ ] Existe respaldo y una versión anterior para volver atrás.
