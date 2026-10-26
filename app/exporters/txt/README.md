# LSD TXT MVP

`lsd.py` genera bytes de longitud fija y permite previsualizarlos como texto. La versión
`mvp-2026.1` preserva los anchos solicitados: 01 (35), 02 (115), 03 (51), 04 (370),
05 (65), 06 (108) y conceptos (195). El contenido usa caracteres ASCII y se codifica
como Latin-1 (`ANSI` de un byte); la vista previa se decodifica con la misma codificación.

Este MVP valida estructura, fechas, CUIT/CUIL, importes, ASCII, orden de registros y
coherencia de trabajadores. No afirma aceptación oficial de ARCA ni reemplaza la
validación contra una especificación aprobada.

- `shortcut:` las posiciones de 01 a 04 siguen campos de una implementación anterior
  disponible en el repositorio de referencia; falta contrastarlas con la revisión oficial
  aplicable al empleador.
- `shortcut:` el detalle oficial completo de 05, 06 y conceptos no está disponible aquí;
  esos layouts mantienen el ancho requerido mediante campos configurables de reserva.
- `shortcut:` el layout de conceptos es una estructura de intercambio de muestra y requiere
  aprobación de códigos, indicadores y offsets antes de cualquier presentación.
