# Convenios Colectivos de Trabajo (CCT) de Argentina: Investigación y Catálogo Normativo

## 1. Advertencia Legal, Metodológica y de Veracidad de Datos

> [!WARNING]
> Este catálogo y la documentación adjunta **no constituyen asesoramiento legal, contable ni laboral**. La normativa laboral y las escalas salariales en la República Argentina están sujetas a acuerdos paritarios periódicos, resoluciones homologatorias de la Secretaría de Trabajo, Empleo y Seguridad Social (Ministerio de Capital Humano) y disposiciones específicas de cada actividad.
>
> Los valores y escalas consignados en este repositorio tienen fines estrictamente técnicos y de modelado para el motor de liquidación (`payroll_engine`). Toda liquidación real debe ser contrastada y verificada por un profesional habilitado frente a las resoluciones homologadas vigentes a la fecha devengada.

### Advertencia sobre representatividad y coberturas estimadas
En la República Argentina **no existe un ranking oficial único ni un registro o padrón estatal centralizado** que certifique legalmente la cantidad exacta de trabajadores amparados por cada convenio colectivo de trabajo de forma individual.
- La Secretaría de Trabajo / Ministerio de Capital Humano y el Sistema Integrado Previsional Argentino (SIPA / OEDE) publican series estadísticas agregadas por rama de actividad económica según el clasificador CLAE/CIIU, pero no desglosan nóminas por número de CCT.
- Por tanto, **todas las cifras de cobertura indicadas en este catálogo son estimaciones sectoriales informativas** provistas por las partes paritarias signatarias (federaciones sindicales con personería gremial y cámaras empresarias) o entidades técnicas sectoriales (ej. IERIC en construcción o BCRA en banca), y no constituyen censos estatales auditados. Donde no existe fuente comprobable de las partes, se indica expresamente *"sin dato oficial centralizado"*.

---

## 2. Criterios de evidencia

- `salary_scales` incluye exclusivamente entradas con `status: verified` en el `scales.json` del expediente correspondiente. Las escalas `unverified` y sus valores estimados permanecen en evidencia y no se cargan al catálogo.
- Cada escala conserva `source_id` y `verification_source`; las categorías y vigencias se copian de la evidencia sin combinar categorías, zonas ni modalidades.
- Los PDF crudos de evidencia no se versionan por su tamaño. Sus URL y hashes SHA-256 están registrados en `sources.json`; los documentos HTML institucionales sí se conservan en cada expediente. Los textos base de los CCT en `normative/cct/pdfs/` se mantienen aparte.
- La fecha de actualización de los expedientes es el 26 de octubre de 2026. Algunas escalas verificadas pueden tener `vigencia_desde` posterior a esa fecha porque el acuerdo ya programa un tramo futuro; esa fecha no significa que el tramo esté vigente hoy.

## 3. Cobertura de evidencia por CCT

| Código CCT | Documentos | Escalas verificadas | Último período verificado | Vacíos u observaciones |
|---|---:|---:|---|---|
| 130/75 | 25 | 290 | 2026-09-01 a 2026-11-30 | Serie 2020–2023 incorporada desde la referencia (13 ventanas, confidence medium). Sin escalas para diciembre de 2026 en adelante. ([fuentes](<evidence/cct_130_75/sources.json>)) |
| 260/75 | 15 | 51 | 2026-12-01 a 2026-12-31 | Solo rama 17 (D-5: carga total de ramas pendiente); serie 2020–2023 parcial (4 ventanas, 14 categorías/ventana sin contraparte). ([fuentes](<evidence/cct_260_75/sources.json>)) |
| 76/75 | 44 | 89 | 2026-11-01 a 2026-11-30 | Serie 2020–2023 parcial (13 ventanas; ventana 2022-02/04 excluida por contradecir planilla homologada). Zona parcial; noviembre 2026 futuro al relevamiento. ([fuentes](<evidence/cct_76_75/sources.json>)) |
| 18/75 | 33 | 17 | 2026-09-01 a 2026-11-06 | Las grillas completas son escaneos sin OCR; los importes verificados son un subconjunto publicado oficialmente. ADVERTENCIA V2-18: `ADMIN_1`/`JEFE_SECCION` 2026 son `unverified` y no entran al catálogo; bloquear categoría sin cobertura. ([fuentes](<evidence/cct_18_75/sources.json>)) |
| 40/89 | 31 | 64 | 2026-09-01 a 2027-02-28 | Re-tecleadas planillas firmadas Sep-2025, Ene-2026 y Mar-2026 (30 escalas). Bache restante: 2025-03..08, 2025-10..12, 2026-02, 2026-04..08. ([fuentes](<evidence/cct_40_89/sources.json>)) |
| 389/04 | 21 | 22 | 2026-06-01 a 2026-09-30 | COCINERO/MOZO del primer tramo 2026 transcriptos de la referencia (confidence medium, cotejo pendiente); resto de roles y segundo tramo pendientes. ([fuentes](<evidence/cct_389_04/sources.json>)) |
| 122/75 | 29 | 95 | 2026-10-01 a 2026-10-31 | Serie 2020–2023 parcial (6 ventanas; 4 categorías/ventana sin contraparte). Anexos históricos escaneados requieren OCR. ([fuentes](<evidence/cct_122_75/sources.json>)) |
| 264/95 | 11 | 30 | 2026-10-01 a 2026-10-31 | Adicionales 2026 re-tecleados (8 escalas); básicos 2026 sin cargar por imposibilidad confirmada B-38R (totales con adicional por jornada sin mínimo garantizado 2026; 2 placeholders `unverified` fuera del catálogo); sin escalas 2024-03..2026-04. ([fuentes](<evidence/cct_264_95/sources.json>)) |
| 244/94 | 26 | 48 | 2026-12-01 a 2026-12-31 | Serie 2020–2022 (5 ventanas; 2023 ausente también en la referencia). 14 categorías/ventana sin contraparte. ([fuentes](<evidence/cct_244_94/sources.json>)) |
| 507/07 | 17 | 32 | 2026-12-01 a 2026-12-31 | Las ocho escalas históricas de 2007 se conservan solo con historical: true. ([fuentes](<evidence/cct_507_07/sources.json>)) |
| 589/10 | 2 | 48 | 2026-07-01 a 2026-09-30 | Alta B-19 desde la referencia (48 escalas 2020–2026, confidence medium, cotejo directo pendiente). ([fuentes](<evidence/cct_589_10/sources.json>)) |

Los once expedientes reúnen **254 documentos** y **786 escalas verificadas**. El último período es el de mayor `vigencia_desde` entre las escalas verificadas de cada CCT; puede ser futuro y no representa una vigencia universal para todas las categorías.

## 4. Catálogo y limitaciones de cobertura

El catálogo conserva los textos base, categorías y fórmulas normativas existentes. La evidencia salarial es parcial por categoría, zona, rama y período; un valor ausente no significa que no exista un acuerdo salarial. Consultar `notes.md` y `scales.json` en cada expediente para búsquedas negativas y escalas no verificadas.

## 5. Fórmulas DSL Validadas (`normative/cct/formulas.json`)

Se elaboraron y validaron **24 fórmulas declarativas DSL** para el motor de nómina (`payroll_engine`), cubriendo los 11 convenios colectivos. Cada fórmula cumple con las siguientes garantías de verificación:
1. **Validación formal:** Valida formalmente contra el modelo Pydantic `FormulaDefinition` y contra el validador estructural de árbol sintáctico `validate_formula()`.
2. **Determinismo y seguridad:** Ninguna fórmula contiene código ejecutable Python arbitrario; todas las operaciones utilizan operadores DSL seguros (`multiply`, `add`, `divide`, `if`, etc.).
3. **Parametrización estricta:** Si una fórmula requiere importes o porcentajes que varían con acuerdos paritarios, se definen como parámetros obligatorios de entrada (`parameters`), impidiendo la inclusión de valores no verificados como constantes numéricas.
4. **Reproducibilidad:** Cada fórmula incluye casos de prueba con entradas (`variables`, `parameters`, `concepts`) y resultados esperados verificados con precisión decimal.

| Código de Fórmula | CCT Asociado | Concepto / Artículo | Naturaleza | Parámetros Requeridos |
|---|---|---|---|---|
| `CCT_130_75_ANTIGUEDAD` | 130/75 | Adicional antigüedad 1% (Art. 24) | `REMUNERATIVE` | `cct13075_porcentaje_antiguedad` |
| `CCT_130_75_PRESENTISMO` | 130/75 | Asignación asistencia y puntualidad 1/12 (Art. 40 + Acuerdo 07/2026: incluye sumas NR, hasta 1 ausencia) | `REMUNERATIVE` | (constante legal 12; variable `dias_ausentes` ≤ 1; concepto `CCT_130_75_SUMA_NR_MENSUAL`) |
| `CCT_130_75_SUMA_NR_MENSUAL` | 130/75 | Suma NR mensual $120.000 + $25.000 extraordinarios jul-ago 2026 (Acuerdo 07/2026) | `NON_REMUNERATIVE` | `cct13075_suma_nr_mensual` |
| `CCT_76_75_ASISTENCIA` | 76/75 | Adicional asistencia perfecta 20% (Art. 52) | `REMUNERATIVE` | `cct7675_porcentaje_asistencia` |
| `CCT_76_75_FONDO_CESE` | 76/75 | Aporte Fondo de Cese 12% / 8% (Ley 22.250 Art. 15) | `CONTRIBUTION` | `cct7675_tasa_fondo_primer_anio`, `cct7675_tasa_fondo_segundo_anio` |
| `CCT_260_75_ANTIGUEDAD` | 260/75 | Escalafón antigüedad 1% (Art. 27) | `REMUNERATIVE` | `cct26075_porcentaje_antiguedad` |
| `CCT_18_75_FALLA_CAJA` | 18/75 | Adicional mensual falla de caja (Art. 22) | `REMUNERATIVE` | `bancarios_sueldo_inicial`, `cct1875_porcentaje_falla_caja` |
| `CCT_40_89_ANTIGUEDAD` | 40/89 | Adicional antigüedad 1% (Art. 6.1.5) | `REMUNERATIVE` | `cct4089_porcentaje_antiguedad` |
| `CCT_40_89_COMIDA` | 40/89 | Viático no remunerativo comida (Art. 4.1.12) | `NON_REMUNERATIVE` | `cct4089_valor_comida_diaria` |
| `CCT_389_04_ASISTENCIA` | 389/04 | Adicional asistencia perfecta 10% (Punto 11.5 oficial; 11.4 en compilación secundaria) | `REMUNERATIVE` | `cct38904_porcentaje_asistencia` |
| `CCT_389_04_COMPLEMENTO_SERVICIO` | 389/04 | Complemento de Servicio 12% (Punto 11.6 oficial; 11.5 en compilación secundaria) | `REMUNERATIVE` | `cct38904_porcentaje_complemento` |
| `CCT_244_94_SUMA_EXTRAORDINARIA_NR` | 244/94 | Suma NR por única vez $150.000 (Acuerdo 22/10/2026, 2 cuotas) | `NON_REMUNERATIVE` | `cct24494_suma_extraordinaria_nr` |
| `CCT_122_75_SUMA_NR_MENSUAL` | 122/75 | Asignación NR mensual $80/70/60k (Acuerdo 15/10/2026) | `NON_REMUNERATIVE` | `cct12275_suma_nr_mensual` |
| `CCT_122_75_DIA_SANIDAD` | 122/75 | Día Sanidad 21/09 pago único $70.304,21 | `NON_REMUNERATIVE` | `cct12275_dia_sanidad` |
| `CCT_507_07_PRESENTISMO` | 507/07 | Presentismo mensual por categoría (Anexo X 06/07/2026) | `REMUNERATIVE` | `cct50707_presentismo_mensual` |
| `CCT_507_07_VIATICO` | 507/07 | Viático NR por día trabajado (Anexo X 06/07/2026) | `NON_REMUNERATIVE` | `cct50707_viatico_diario`, `dias_trabajados` |
| `CCT_122_75_ESCALAFON` | 122/75 | Escalafón antigüedad 2% anual (Art. 10) | `REMUNERATIVE` | `cct12275_tasa_escalafon_anual` |
| `CCT_507_07_ANTIGUEDAD` | 507/07 | Bonificación antigüedad 1% (Art. 24) | `REMUNERATIVE` | `cct50707_porcentaje_antiguedad` |
| `CCT_264_95_FALLA_CAJA` | 264/95 | Falla de caja 20% Grupo I (Cláusula 10°) | `REMUNERATIVE` | `seguros_sueldo_minimo_grupo_i`, `cct26495_alicuota_falla_caja` |
| `CCT_244_94_ANTIGUEDAD` | 244/94 | Escalafón antigüedad 1%/1,25%/1,5% tope 52,5% (Art. 55) | `REMUNERATIVE` | `cct24494_tasa_antiguedad_1_10`, `cct24494_tasa_antiguedad_11_20`, `cct24494_tasa_antiguedad_21_mas` |
| `CCT_589_10_ANTIGUEDAD` | 589/10 | Bonificación antigüedad 2% (Art. 11) | `REMUNERATIVE` | `cct58910_base_antiguedad`, `cct58910_tasa_antiguedad` |
| `CCT_589_10_TITULO_SERACARH` | 589/10 | Adicional título Encargado Integral 10% | `REMUNERATIVE` | `cct58910_tasa_titulo` |

---

## 6. Revisión de datos de evidencia

El test global `tests/normative/test_cct_evidence.py` comprueba los diez expedientes, las referencias a fuentes, fechas y categorías, y la integridad de archivos locales disponibles. También compara cada `salary_scales` con las entradas `verified` de `scales.json` y realiza un dry-run del loader real.

## 7. Limitaciones Normativas Identificadas

1. **Dinámica Paritaria:** En Argentina las escalas de los convenios colectivos se actualizan periódicamente (mensual, bimestral o trimestralmente) mediante acuerdos celebrados en paritarias y homologados por la Secretaría de Trabajo.
2. **Sumas No Remunerativas Complejas:** Los acuerdos paritarios recientes con frecuencia incorporan asignaciones no remunerativas transitorias con aportes parciales a obras sociales o sindicatos, cuya desagregación impositiva debe modelarse a nivel de bases imponibles particulares.
3. **Dispersión de Ramas Internas:** Convenios extensos como UOM 260/75 y Camioneros 40/89 poseen decenas de ramas y anexos específicos (ej. siderurgia, transporte de caudales, combustibles). El catálogo contempla la estructura marco general y las categorías de mayor representatividad.
