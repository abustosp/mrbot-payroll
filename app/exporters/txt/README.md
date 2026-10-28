# LSD TXT

`lsd.py` genera archivos de longitud fija y permite previsualizarlos como
texto. Los layouts espejan las herramientas oficiales de ARCA para "Libro de
Sueldos Digital" (Ayuda > Herramientas de trabajo):
`LSD-ARMADO-TXT-Liquidaciones.xlsx` (reg 01-06) y
`LSD-ARMADO-TXT-Conceptos.xlsx` (hoja "Interfase", conceptos de 195
posiciones). Versión `afip-2025.09`: 01 (35), 02 (115), 03 (51), 04 (370),
05 (65), 06 (93) y conceptos (195, sin prefijo de tipo de registro).

El contenido usa caracteres ASCII y se codifica como Latin-1; las líneas se
separan con CRLF. La vista previa se decodifica con la misma codificación.

Detalles de fidelidad con la herramienta oficial:

- 02: CBU alineado a derecha con espacios; fecha de rúbrica con espacios
  (no ceros) cuando está presente; forma de pago con ceros.
- 03: cantidad con formato 999,99 (5 dígitos, ceros); período de ajuste
  `AAAAMM` o en blanco (6 espacios).
- 04: actividad, localidad y obra social con ceros; condición, modalidad y
  siniestrado alineados a izquierda con espacios; bases e importes con
  formato de 15 dígitos (13 enteros + 2 decimales).
- 05: categoría (6, ceros) + puesto (4, ceros) de Simplificación Registral,
  fechas con ceros, remuneración de 15 dígitos y CUIT del empleador eventual.
- 06: 93 posiciones sin campo período; la observación se rellena con ceros
  a izquierda hasta 80.
- Conceptos: código ARCA (6) + código empleador (10) + descripción (150) +
  marca de repetición + 19 banderas/reservas en posiciones fijas
  (SIPA/AP-CONTRIB ... regímenes diferenciales/especiales) + 9 blancos.

Este generador solo emite envíos "SJ" (el 01 lleva días base numéricos; el
formulario en blanco de días es exclusivo de archivos "RE", que no se
generan aquí). Es un borrador sin validez ante ARCA y no reemplaza las
validaciones oficiales.
