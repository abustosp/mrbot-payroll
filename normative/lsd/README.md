# Diseños oficiales TXT del Libro de Sueldos Digital

Fuente: [página de diseños de ARCA](https://www.afip.gob.ar/LibrodeSueldosDigital/ayuda/disenios.asp)
y [herramientas de trabajo](https://www.afip.gob.ar/LibrodeSueldosDigital/ayuda/planillas-de-calculo.asp).
Recuperados el 2026-10-27; los hashes están en [catalog.json](catalog.json).

## Convención

Igual que `normative/cct/evidence`: los binarios **no** se versionan.
`catalog.json` registra `source_url` + `sha256` para re-descargar y verificar.
La etiqueta interna `LAYOUT_VERSION = "afip-2025.09"` en
`app/exporters/txt/lsd.py` corresponde a la herramienta oficial
`LSD-ARMADO-TXT-Liquidaciones.xlsx` (2025-09-22).

## Qué se contrastó

- Anchos de registro 01 (35), 02 (115), 03 (51), 04 (370), 05 (65), 06 (93)
  y maestro de conceptos (195): idénticos en diseño y herramienta.
- Rellenos: CBU espacios a izquierda, pago con ceros, rúbrica con espacios,
  forma de pago con ceros; 03 `TEXT(*100)`; 04 numéricos con ceros salvo
  condición/modalidad/siniestrado (espacios); 05 ceros; 06 observación con
  ceros a izquierda; conceptos banderas en posiciones 167-186 + 9 blancos.
- Divergencia conocida y documentada en `app/exporters/txt/lsd.py`: el
  registro 01 sin `base_days` emite `00`, la herramienta emite 2 blancos
  (formulario en blanco reservado a archivos RE, que no se generan; la ruta
  real siempre fija `base_days = 30`).

El TXT generado sigue siendo **borrador sin validez ante ARCA** (no reemplaza
las validaciones oficiales).
