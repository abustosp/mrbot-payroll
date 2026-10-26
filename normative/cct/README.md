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
| 130/75 | 9 | 17 | 2026-09-01 a 2026-11-30 | No hay escalas verificadas de 2020–2023 ni para diciembre de 2026 en adelante. ([fuentes](<evidence/cct_130_75/sources.json>)) |
| 260/75 | 10 | 23 | 2026-12-01 a 2026-12-31 | La evidencia verificada disponible corresponde a la rama 17; no consolida todas las ramas del convenio. ([fuentes](<evidence/cct_260_75/sources.json>)) |
| 76/75 | 29 | 24 | 2026-11-01 a 2026-11-30 | La cobertura por zona es parcial; las vigencias de noviembre de 2026 son futuras al relevamiento del 26/10/2026. ([fuentes](<evidence/cct_76_75/sources.json>)) |
| 18/75 | 31 | 17 | 2026-09-01 a 2026-11-06 | Las grillas completas son escaneos sin OCR; los importes verificados son un subconjunto publicado oficialmente. ([fuentes](<evidence/cct_18_75/sources.json>)) |
| 40/89 | 21 | 28 | 2025-02-01 a 2025-02-28 | No hay escalas verificadas posteriores a febrero de 2025; las proyecciones 2026 quedan fuera del catálogo. ([fuentes](<evidence/cct_40_89/sources.json>)) |
| 389/04 | 19 | 20 | 2024-05-01 a 2024-05-31 | No hay escalas verificadas posteriores a mayo de 2024; los acuerdos 2026 no aportan importes verificados en esta evidencia. ([fuentes](<evidence/cct_389_04/sources.json>)) |
| 122/75 | 23 | 29 | 2026-10-01 a 2026-10-31 | Sin escalas verificadas de 2020–2023; varios anexos históricos escaneados requieren OCR. ([fuentes](<evidence/cct_122_75/sources.json>)) |
| 264/95 | 11 | 22 | 2024-02-01 a 2024-02-29 | No hay escalas verificadas posteriores a febrero de 2024; la grilla 2026 requiere OCR. ([fuentes](<evidence/cct_264_95/sources.json>)) |
| 244/94 | 21 | 23 | 2026-12-01 a 2026-12-31 | No hay escalas verificadas de 2020–2023; hay tramos programados posteriores a la fecha de búsqueda. ([fuentes](<evidence/cct_244_94/sources.json>)) |
| 507/07 | 17 | 32 | 2026-12-01 a 2026-12-31 | Las ocho escalas históricas de 2007 se conservan solo con historical: true. ([fuentes](<evidence/cct_507_07/sources.json>)) |

Los diez expedientes reúnen **191 documentos** y **235 escalas verificadas**. El último período es el de mayor `vigencia_desde` entre las escalas verificadas de cada CCT; puede ser futuro y no representa una vigencia universal para todas las categorías.

## 4. Catálogo y limitaciones de cobertura

El catálogo conserva los textos base, categorías y fórmulas normativas existentes. La evidencia salarial es parcial por categoría, zona, rama y período; un valor ausente no significa que no exista un acuerdo salarial. Consultar `notes.md` y `scales.json` en cada expediente para búsquedas negativas y escalas no verificadas.

## 5. Fórmulas DSL Validadas (`normative/cct/formulas.json`)

Se elaboraron y validaron **12 fórmulas declarativas DSL** para el motor de nómina (`payroll_engine`), cubriendo los 10 convenios colectivos. Cada fórmula cumple con las siguientes garantías de verificación:
1. **Validación formal:** Valida formalmente contra el modelo Pydantic `FormulaDefinition` y contra el validador estructural de árbol sintáctico `validate_formula()`.
2. **Determinismo y seguridad:** Ninguna fórmula contiene código ejecutable Python arbitrario; todas las operaciones utilizan operadores DSL seguros (`multiply`, `add`, `divide`, `if`, etc.).
3. **Parametrización estricta:** Si una fórmula requiere importes o porcentajes que varían con acuerdos paritarios, se definen como parámetros obligatorios de entrada (`parameters`), impidiendo la inclusión de valores no verificados como constantes numéricas.
4. **Reproducibilidad:** Cada fórmula incluye casos de prueba con entradas (`variables`, `parameters`, `concepts`) y resultados esperados verificados con precisión decimal.

| Código de Fórmula | CCT Asociado | Concepto / Artículo | Naturaleza | Parámetros Requeridos |
|---|---|---|---|---|
| `CCT_130_75_ANTIGUEDAD` | 130/75 | Adicional antigüedad 1% (Art. 24) | `REMUNERATIVE` | `cct13075_porcentaje_antiguedad` |
| `CCT_130_75_PRESENTISMO` | 130/75 | Asignación asistencia y puntualidad 1/12 (Art. 40) | `REMUNERATIVE` | (constante legal 12) |
| `CCT_76_75_ASISTENCIA` | 76/75 | Adicional asistencia perfecta 20% (Art. 52) | `REMUNERATIVE` | `cct7675_porcentaje_asistencia` |
| `CCT_76_75_FONDO_CESE` | 76/75 | Aporte Fondo de Cese 12% / 8% (Ley 22.250 Art. 15) | `CONTRIBUTION` | `cct7675_tasa_fondo_primer_anio`, `cct7675_tasa_fondo_segundo_anio` |
| `CCT_260_75_ANTIGUEDAD` | 260/75 | Escalafón antigüedad 1% (Art. 27) | `REMUNERATIVE` | `cct26075_porcentaje_antiguedad` |
| `CCT_18_75_FALLA_CAJA` | 18/75 | Adicional mensual falla de caja (Art. 22) | `REMUNERATIVE` | `bancarios_sueldo_inicial`, `cct1875_porcentaje_falla_caja` |
| `CCT_40_89_ANTIGUEDAD` | 40/89 | Adicional antigüedad 1% (Art. 6.1.5) | `REMUNERATIVE` | `cct4089_porcentaje_antiguedad` |
| `CCT_40_89_COMIDA` | 40/89 | Viático no remunerativo comida (Art. 4.1.12) | `NON_REMUNERATIVE` | `cct4089_valor_comida_diaria` |
| `CCT_389_04_ASISTENCIA` | 389/04 | Adicional asistencia perfecta 10% (Punto 11.5) | `REMUNERATIVE` | `cct38904_porcentaje_asistencia` |
| `CCT_122_75_ESCALAFON` | 122/75 | Escalafón antigüedad 2% anual (Art. 10) | `REMUNERATIVE` | `cct12275_tasa_escalafon_anual` |
| `CCT_507_07_ANTIGUEDAD` | 507/07 | Bonificación antigüedad 1% (Art. 24) | `REMUNERATIVE` | `cct50707_porcentaje_antiguedad` |
| `CCT_264_95_FALLA_CAJA` | 264/95 | Falla de caja 20% Grupo I (Cláusula 10°) | `REMUNERATIVE` | `seguros_sueldo_minimo_grupo_i`, `cct26495_alicuota_falla_caja` |

---

## 6. Revisión de datos de evidencia

El test global `tests/normative/test_cct_evidence.py` comprueba los diez expedientes, las referencias a fuentes, fechas y categorías, y la integridad de archivos locales disponibles. También compara cada `salary_scales` con las entradas `verified` de `scales.json` y realiza un dry-run del loader real.

## 7. Limitaciones Normativas Identificadas

1. **Dinámica Paritaria:** En Argentina las escalas de los convenios colectivos se actualizan periódicamente (mensual, bimestral o trimestralmente) mediante acuerdos celebrados en paritarias y homologados por la Secretaría de Trabajo.
2. **Sumas No Remunerativas Complejas:** Los acuerdos paritarios recientes con frecuencia incorporan asignaciones no remunerativas transitorias con aportes parciales a obras sociales o sindicatos, cuya desagregación impositiva debe modelarse a nivel de bases imponibles particulares.
3. **Dispersión de Ramas Internas:** Convenios extensos como UOM 260/75 y Camioneros 40/89 poseen decenas de ramas y anexos específicos (ej. siderurgia, transporte de caudales, combustibles). El catálogo contempla la estructura marco general y las categorías de mayor representatividad.
