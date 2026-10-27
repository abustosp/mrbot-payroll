# Evidencia Normativa y Salarial - CCT 18/75 (Bancarios)

## 1. Resumen Ejecutivo

El Convenio Colectivo de Trabajo N° 18/75 rige las condiciones laborales y remunerativas de los trabajadores del sector bancario y financiero en todo el territorio argentino. Es suscripto entre la **Asociación Bancaria (Sociedad de Empleados de Banco)** y las cuatro cámaras representativas del sistema financiero:
- **ABAPPRA:** Asociación de Bancos Públicos y Privados de la República Argentina.
- **ADEBA:** Asociación de Bancos Argentinos (bancos de capital nacional).
- **ABA:** Asociación de Bancos de la Argentina (bancos internacionales).
- **ABE:** Asociación de la Banca Especializada.

En este repositorio de evidencia se compilaron y verificaron **31 documentos oficiales** (20 archivos PDF y 11 documentos HTML institucionales) que respaldan las escalas salariales, actas paritarias y fórmulas de cálculo para el período **2020-01-01 hasta 2026-10-26**.

Todos los archivos PDF comienzan con `%PDF-`, cuentan con sus hashes criptográficos SHA-256 verificados en `sources.json`, y los valores fueron confrontados contra los textos de convenio y acuerdos paritarios homologados.

---

## 2. Estructura Salarial Convencional y Fórmulas Clave

### 2.1. Sueldo Inicial Conformado y Participación en Ganancias (ROE)
La remuneración del trabajador bancario ingresante o de escala inicial se compone convencionalmente de dos rubros inescindibles:
1. **Salario Básico Inicial:** Retribución fija mensual del escalafón administrativo inicial.
2. **Participación en las Ganancias (ROE):** Adicional remunerativo derivado del acuerdo sectorial sobre rentabilidad del sistema financiero (Return on Equity).
3. **Salario Inicial Conformado = Salario Básico Inicial + ROE.**

### 2.2. Adicional por Falla de Caja (Art. 22 CCT 18/75)
El Artículo 22 del CCT 18/75 original establece un adicional porcentual obligatorio mensual para todo personal que cumpla funciones de caja, calculado sobre el **Sueldo Básico Inicial**:
- **Cajero Recibidor:** **20%** sobre el sueldo inicial.
- **Cajero Recibidor y Pagador (Mixto):** **30%** sobre el sueldo inicial.
- **Cajero Pagador:** **40%** sobre el sueldo inicial.
- Asimismo, perciben un suplemento por **Falla de Caja en Moneda Extranjera** y el adicional por **Función de Caja**.
- Implementación en motor de nómina: verificado y consistente con la fórmula `CCT_18_75_FALLA_CAJA` en `normative/cct/formulas.json`.

### 2.3. Compensación Extraordinaria por el Día del Bancario
Conforme al CCT 18/75 y acuerdos paritarios complementarios, el **6 de noviembre** se celebra el Día del Bancario (no laborable y asimilado a feriado nacional para el sistema financiero). Todo trabajador percibe una compensación extraordinaria no remunerativa indexada al salario inicial y la antigüedad. Para el año 2026, el acuerdo paritario del 16 de octubre fijó el **piso mínimo en $2.275.519,25**, a liquidarse antes del 06/11/2026.

---

## 3. Dinámica Paritaria e Indexación Mensual (2020 - 2026)

Desde finales de 2023 y durante todo 2024, 2025 y 2026, la Asociación Bancaria y las cuatro cámaras empresariales implementaron un mecanismo paritario de **ajuste mensual automático indexado por el Índice de Precios al Consumidor (IPC)** informado por el INDEC, con carácter retroactivo al primer día del mes analizado.

### 3.1. Escalas Vigentes en 2026 (Moneda ARS)

| Período | Básico Inicial | Participación ROE | Total Inicial Conformado | Día del Bancario (Mínimo) |
| :--- | :--- | :--- | :--- | :--- |
| **Septiembre / Octubre 2026** | **$ 2.552.560,34** | **$ 73.786,55** | **$ 2.626.346,89** | **$ 2.275.519,25** |
| **Agosto 2026** | $ 2.505.061,24 | $ 72.413,50 | $ 2.577.474,74 | $ 2.233.175,44 |
| **Julio 2026** | $ 2.463.757,68 | $ 71.219,54 | $ 2.534.977,22 | $ 2.196.354,74 |
| **Junio 2026** | $ 2.412.128,22 | $ 69.727,10 | $ 2.481.855,32 | $ 2.150.328,87 |
| **Mayo 2026** | $ 2.368.759,48 | $ 68.473,44 | $ 2.437.232,92 | $ 2.111.667,14 |
| **Abril 2026** | — | — | $ 2.319.195,20 | $ 2.067.482,29 |
| **Marzo 2026** | — | — | $ 2.259.305,03 | $ 2.014.092,28 |
| **Febrero 2026** | — | — | $ 2.187.023,79 | $ 1.949.656,06 |
| **Enero 2026** | — | — | $ 2.125.068,44 | $ 1.894.425,01 |
| **Diciembre 2025 (Base)** | $ 2.065.178,27 | $ 59.697,86 | $ 2.124.876,13 | — |

*El acuerdo del 16 de octubre de 2026 estipuló que durante octubre, noviembre y diciembre de 2026 se mantendrá el mismo mecanismo de actualización mensual por IPC, convocando a la reapertura paritaria formal en la segunda quincena de enero de 2027.*

---

## 4. Estado de Verificación y Documentos Escaneados (Regla del Contrato)

Conforme a las pautas establecidas en `normative/cct/EVIDENCE_CONTRACT.md`:
1. **Valores Verificados (`status: verified`):**
   - El Salario Inicial Conformado, el desglose Básico/ROE y el Adicional Falla de Caja se encuentran plenamente verificados con respaldo en comunicados oficiales directos del Secretariado Nacional y actas firmadas.
2. **Grillas Completas Escaneadas (`status: unverified`):**
   - Las planillas de grillas salariales completas de 8 a 11 páginas publicadas mensualmente por el sindicato (`bancarios_grillas_2026_10_octubre.pdf`, `bancarios_grillas_2025_09_septiembre.pdf`, etc.) son imágenes fotocopiadas/escaneadas de planillas contables que carecen de capa de texto embebida digital.
   - En estricta aplicación del contrato, las categorías intermedias y jerárquicas del escalafón (como `ADMIN_1` o `JEFE_SECCION`) se registraron como `unverified` con nota indicando que requieren OCR o transcripción manual certificada para su incorporación automatizada definitiva.

## 4bis. Advertencia de cobertura V2-18 (2026-10-26, sin OCR en el entorno)

**ADVERTENCIA: el catálogo 18/75 cubre solo el subconjunto publicado oficialmente (17 escalas `verified`: INICIAL, INICIAL_ROE, falla de caja y Día del Bancario).**
Las grillas completas intermedias/jerárquicas 2026 (`ADMIN_1` $2.750.000,00 y `JEFE_SECCION` $3.200.000,00 en `scales.json` `unverified`, `src-bancarios-002`, vigencia 2026-09-01 a 2026-10-31) son escaneos sin capa de texto (`pdftotext` devuelve solo form-feeds; sin motor OCR instalado): **no se cargan al catálogo y ninguna liquidación debe usarlas como básico**.
Toda categoría fuera del subconjunto `verified` debe bloquearse o advertirse como "sin cobertura verificada" hasta el OCR/transcripción celda por celda contra `bancarios_grillas_2026_10_octubre.pdf` (12 páginas JPEG 200 dpi) y planillas 2025-06/2026-05..08.

---

## 5. Búsquedas Negativas y Hallazgos

1. **Dominio Histórico Inactivo:**
   - La búsqueda en `bancarios.org.ar` arrojó falla de resolución DNS. La investigación constató que el gremio centralizó todas sus publicaciones en el portal `labancaria.org` y `bancariasba.com.ar`.
2. **Escala 2026 en Catálogo:**
   - En el `catalog.json` original la escala 2026 figuraba en estado `unverified` con un valor estimado de $1.450.000,00. Gracias a la presente evidencia oficial, se verifica que el salario inicial bancario vigente a octubre de 2026 es de **$2.626.346,89**, superando ampliamente las estimaciones previas debido a la aceleración inflacionaria y las cláusulas gatillo acumulativas.
