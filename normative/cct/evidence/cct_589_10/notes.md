# Evidencia CCT 589/10 (Edificios — SUTERH/FATERYH) — 2020 a 2026

## 1. Alcance (B-19)
Alta del CCT 589/10 desde la compilación de referencia (solo lectura):
`00_LEEME_REPOSITORIO_2020_2026.md` (9 CCT troncales, 8 tramos 2020-2026 para 589/10),
`05_Textos_Ordenados.../CCT_589_10_Edificios_SUTERH_Texto_Ordenado_y_Serie_2020_2026.md`
(§2 serie 202006-202607, §3 tabla 2026 por categoría),
`04_Configuracion.../csv_tablas_importacion/03_escalas_historicas_2020_2026.csv`
(88 filas CCT 589/10; se cargan las 48 de categorías funcionales, se excluyen las
pseudo-categorías `HISTORICO_*` que duplican valores) y
`por_convenio/escalas_CCT_589_10_Edificios_SUTERH.csv` (12 filas, vigencia 202606).

## 2. Cadena de evidencia
- `src-589-001` (official): portal institucional SUTERH con el texto ordenado vigente,
  copia local en `html/suterh_cct_589_10.html` (fetch 2026-10-26). Respalda existencia del
  CCT, categorías (Art. 7) y Art. 11 de antigüedad. NO contiene los importes de escala.
- `src-589-002` (official: false): copia local de la compilación de referencia de la que se
  transcriben todos los importes. Cada escala cita en `notes` el CSV y la vigencia origen.
- `confidence: medium` en las 48 escalas: transcripción mediada por compilación secundaria.

## 3. Discrepancias observadas en la referencia (NO silenciadas)
- D1. Art. 11: la referencia resume "1% anual", pero el texto oficial del portal fija
  **2%** por año sobre el básico del ayudante permanente sin vivienda de 4ª categoría para
  jornada completa, y **1%** solo para media jornada/suplente/jornalizados ingresados tras
  la homologación 2009. La fórmula `CCT_589_10_ANTIGUEDAD` implementa la regla general (2%);
  la variante 1% queda como gap (ver reporte fix-convenios.md).
- D2. NR 2026: §2 de la referencia indica +$50.000 NR (202607) pero §3 y el CSV por_convenio
  indican NR $0,00. Se carga `amount` = básico en ambos casos y la NR queda documentada en
  `notes` por escala.
- D3. Vigencia 2026: el CSV por_convenio marca 202606 y la tabla §2 `202607` ("Jun–Sep 2026").
  Se adopta `valid_from` 2026-07-01 / `valid_to` 2026-09-30 (ventana §2).

## 4. Gaps (ver reporte fix-convenios.md)
- G1. Cotejo directo celda por celda contra planilla homologada 2026 pendiente (sin OCR local:
  no hay motor OCR instalado; los PDF oficiales 2026 son escaneos).
  Profundización B-19P (2026-10-26, solo referencia de lectura, sin inventar):
  `03_escalas_historicas_2020_2026.csv` trae 88 filas CCT 589/10 = 48 funcionales cargadas
  (`verified`, `confidence: medium`, `src-589-002`) + 40 `HISTORICO_*` excluidas por duplicar
  valores (pseudo-categorías, no funciones del Art. 7); `por_convenio/escalas_CCT_589_10_Edificios_SUTERH.csv`
  trae 11 filas vigencia 202606 (básicos 4ª categoría) consistentes con la ventana adoptada
  2026-07-01 a 2026-09-30 (D3). No hay planilla homologada 2026 local con capa de texto para
  cotejar: `src-589-001` es texto ordenado sin importes y `src-589-002` es compilación secundaria
  (`official: false`). Por tanto el cotejo G1 sigue pendiente y las 48 escalas conservan
  `confidence: medium` con la advertencia de defensa probatoria limitada (ver 02-legal §B-19).
- G2. Escalas por categoría de edificio (1ª a 4ª) solo testigos en la referencia (4ª categoría);
  el catálogo cubre funciones con valores 4ª categoría.
- G3. Adicionales (retiro residuos, jardín, pileta, presentismo 8,33%, bonificación anual 20%)
  sin fórmula DSL en esta entrega (solo antigüedad Art. 11 y título SERACARH 10%).
