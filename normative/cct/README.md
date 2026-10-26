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

## 2. Metodología y Criterios de Auditoría

### Prioridad de Integridad de Datos frente a Exhaustividad
1. **Verificación Estricta de Escalas Salariales:**
   - Una escala salarial solo puede ostentar el estado `verified` si la combinación exacta de **categoría, importe, moneda, vigencia y fuente** se encuentra respaldada en un documento oficial descargado en `normative/cct/pdfs/` o en una resolución estatal comprobable.
   - Si no se cuenta con el acta paritaria oficial homologada en el repositorio, la escala debe constar como `unverified`, con `importe: null` y, en su caso, el valor de referencia trasladado al campo `estimated_value` acompañado de una nota de verificación explicativa.
2. **Resguardo de Textos Originales:**
   - Los 10 convenios colectivos cuentan con su documento base en formato PDF en `normative/cct/pdfs/`, con cabecera `%PDF` válida y hash criptográfico SHA-256 verificado.
   - Se preservan intactos los textos ordenados históricos (1975, 1989, 1994, 1995, 2004, 2007) que dan sustento formal a los artículos y fórmulas normativas.
3. **Parametrización Declarativa de Fórmulas:**
   - Las 12 fórmulas DSL del catálogo se sustentan en los artículos normativos de los textos base.
   - Ninguna fórmula incorpora valores salariales no verificados como constantes numéricas fijas; todos los valores dinámicos operan como parámetros requeridos de cálculo.

---

## 3. Catálogo de los 10 Convenios y Estado de Verificación

| # | Código CCT | Denominación y Actividad | Sindicato Signatario | Cámaras Empresarias | Cobertura Estimada (Fuente) | Escalas Salariales | Archivo PDF Oficial | SHA-256 Checksum |
|---|---|---|---|---|---|---|---|---|
| 1 | **130/75** | Empleados de Comercio y Servicios (Rama General) | FAECYS | CAC, CAME, UDECA | ~1.200.000 (Estimación paritaria FAECYS/CAC) | **Pendiente** (4 escalas no verificadas) | [`cct_130_75.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_130_75.pdf) | `85ad67c9fc049dfd222bb04fefee2e76fc70a9893841f4e7e5a93d0c15d183a9` |
| 2 | **260/75** | Industria Metalúrgica | UOMRA | ADIMRA, CAMIMA, AFAC, FEDEHOGAR, CAIAMA | ~180.000 - 220.000 (Estimación gremial UOMRA) | **Pendiente** (2 escalas no verificadas) | [`cct_260_75.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_260_75.pdf) | `985421aa7e86bbcddb23f51c2264893ba0bc378bea1615f834174402c99ea84e` |
| 3 | **76/75** | Obreros de la Industria de la Construcción | UOCRA | CAMARCO, FAEC, Centro de Arquitectos | ~350.000 - 400.000 (Estadística mensual IERIC) | **Pendiente** (4 escalas no verificadas) | [`cct_76_75.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_76_75.pdf) | `25c7e43e209c09767f7c61e25df8197e89d8e53b10d2e4800b4b85f62bcd24e1` |
| 4 | **18/75** | Personal Bancario y Financiero | Asociación Bancaria | ABAPPRA, ADEBA, ABA, ABE, BCRA | ~90.000 - 95.000 (Dotación estimada s/ informes BCRA) | **Pendiente** (1 escala no verificada) | [`cct_18_75.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_18_75.pdf) | `f26c04f3de75c99627c74b13d1719b2e3199fd63296487444392641bc2961bcf` |
| 5 | **40/89** | Transporte Automotor de Cargas y Logística | FEDCAM | FADEEAC, CATAC | ~150.000 - 200.000 (Estimación gremial FEDCAM/FADEEAC) | **Pendiente** (2 escalas no verificadas) | [`cct_40_89.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_40_89.pdf) | `d52b2bae0abb69492ee3760044ead5cf576fc32470ca1a70cb3ea58f17916810` |
| 6 | **389/04** | Actividad Hotelera y Gastronómica | UTHGRA | FEHGRA, AHRCC | ~200.000 - 250.000 (Estimación paritaria UTHGRA/FEHGRA) | **Pendiente** (2 escalas no verificadas) | [`cct_389_04.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_389_04.pdf) | `302a2d1f94a3d72489992dac8276247e5ccaf041a8e444836bc749f4d4ef8d61` |
| 7 | **122/75** | Sanidad (Clínicas, Sanatorios y Hospitales Privados) | FATSA | ADECRA, CEDIM, CEPSAL, CONFECLISA | ~200.000 - 220.000 (Estimación sectorial FATSA/ADECRA) | **Pendiente** (2 escalas no verificadas) | [`cct_122_75.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_122_75.pdf) | `debda11d0e473ab17c77566e921ca810f926cdb9bab1395d4787b630940729bd` |
| 8 | **264/95** | Actividad Aseguradora y Reaseguros | Sindicato del Seguro | AACS, ADEAA, UART, ADIRA | ~50.000 - 55.000 (Estimación sectorial SSN / Gremio) | **Pendiente** (2 escalas no verificadas) | [`cct_264_95.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_264_95.pdf) | `546a5095ba62bc2b7780482a8c28600e6fead834fd916ad8cfa4a5b2e03a285c` |
| 9 | **244/94** | Industrias de la Alimentación | FTIA | FIPAA y cámaras asociadas | ~100.000 - 110.000 (Estimación gremial FTIA) | **Pendiente** (2 escalas no verificadas) | [`cct_244_94.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_244_94.pdf) | `089ed72b1dc6fd1867232aa0378847c4686b637a6efbda5cd3a2b014d35f0c42` |
| 10 | **507/07** | Seguridad y Vigilancia Privada | UPSRA | CAESI | ~100.000 - 130.000 (Estimación gremial CAESI/UPSRA) | **Verificado** (8 escalas en Res. 732/07) | [`cct_507_07.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_507_07.pdf) | `96499621c5ea6ab613e0ce32c19b55fc984241bb32c2c4041e6509571e256cc8` |

---

## 4. Detalle de Convenios y Particularidades Técnicas

### 1. Comercio y Servicios (CCT 130/75)
- **Representatividad y Cobertura:** Principal convenio colectivo privado de la economía argentina. Cobertura estimada por FAECYS y cámaras mercantiles (CAC/CAME) en ~1.200.000 dependientes; sin padrón oficial centralizado por parte del Estado.
- **Estado de escalas:** Escalas 2026 en estado `unverified` (`importe: null`, valor técnico en `estimated_value`). El repositorio cuenta con el texto histórico del CCT 130/75 (`cct_130_75.pdf`), pero no con el acta paritaria 2026 oficial homologada.
- **Particularidades técnicas:** Estructura en 6 agrupamientos (Maestranza, Administrativo, Cajeros, Auxiliares, Auxiliares Especializados y Ventas). Adicional antigüedad 1% (Art. 24) y presentismo 1/12 (8,3333%) de la remuneración mensual (Art. 40).

### 2. Industria Metalúrgica (CCT 260/75)
- **Representatividad y Cobertura:** Convenio medular del sector manufacturero argentino. Cobertura estimada por UOMRA en ~180.000 - 220.000 dependientes; sin registro estatal desagregado por CCT.
- **Estado de escalas:** Escalas 2026 en estado `unverified` (`importe: null`, valor de referencia en `estimated_value`) al carecer de acta paritaria oficial homologada en el repositorio.
- **Particularidades técnicas:** Convivencia de personal mensualizado y jornalizado por hora. Escalafón por antigüedad del 1% por año cumplido (Art. 27).

### 3. Industria de la Construcción (CCT 76/75)
- **Representatividad y Cobertura:** Abarca obras de ingeniería y arquitectura privadas y públicas. Cobertura estimada entre ~350.000 y 400.000 obreros según los informes periódicos del IERIC (Instituto de Estadística y Registro de la Industria de la Construcción).
- **Estado de escalas:** Escalas en estado `unverified` (`importe: null`). El texto original del CCT 76/75 (Art. 47) contiene jornales diarios fijados en **Pesos Ley 18.188 ($L)** discriminados por zonas geográficas (Zona A Oficial: $ 260,73; Zona C Sereno: $ 5.105,70), no en Pesos (ARS). Los valores no surgen como moneda de curso legal vigente ni se cuenta con acta paritaria reciente homologada en el repositorio.
- **Particularidades técnicas:** Régimen especial de la **Ley 22.250** con aporte patronal al Fondo de Cese Laboral (12% durante el primer año y 8% a partir del segundo). Adicional por asistencia perfecta quincenal del 20% sobre el básico (Art. 52).

### 4. Personal Bancario y Financiero (CCT 18/75)
- **Representatividad y Cobertura:** Dotación estimada en ~90.000 - 95.000 trabajadores en entidades financieras y cambiarias, conforme a los Informes sobre Bancos del Banco Central de la República Argentina (BCRA) y la Asociación Bancaria.
- **Estado de escalas:** Escalas 2026 en estado `unverified` (`importe: null`, valor en `estimated_value`) por ausencia de acta paritaria homologada en el repositorio.
- **Particularidades técnicas:** Escalafón de antigüedad y adicional mensual por falla de caja (Art. 22: 20% recibidor, 40% pagador, 30% mixto sobre sueldo inicial).

### 5. Transporte Automotor de Cargas (CCT 40/89)
- **Representatividad y Cobertura:** Cobertura estimada por FEDCAM y FADEEAC en ~150.000 - 200.000 choferes y operarios en logística y distribución nacional; sin dato oficial centralizado por CCT.
- **Estado de escalas:** Escalas 2026 en estado `unverified` (`importe: null`) por falta de acta paritaria homologada en el repositorio.
- **Particularidades técnicas:** Viáticos no remunerativos por día trabajado (comida Art. 4.1.12, pernoctada Art. 4.1.14) y régimen de horas por kilometraje recorrido (Art. 4.2.3). Adicional de antigüedad del 1% anual (Art. 6.1.5).

### 6. Actividad Hotelera y Gastronómica (CCT 389/04)
- **Representatividad y Cobertura:** Cobertura estimada por UTHGRA y FEHGRA en ~200.000 - 250.000 trabajadores del sector gastronómico y hotelero; sin padrón oficial unificado.
- **Estado de escalas:** Escalas 2026 en estado `unverified` (`importe: null`) por no disponer de acta paritaria homologada en el repositorio.
- **Particularidades técnicas:** Adicional por asistencia perfecta mensual del 10% del básico (Punto 11.5) y complemento de servicio (Punto 11.6).

### 7. Sanidad Privada - Asistenciales (CCT 122/75)
- **Representatividad y Cobertura:** Cobertura estimada por FATSA y cámaras prestadoras (ADECRA) en ~200.000 - 220.000 dependientes en sanatorios, clínicas y hospitales privados; sin registro estatal desglosado.
- **Estado de escalas:** Escalas 2026 en estado `unverified` (`importe: null`) por carecer de acta homologada en el repositorio.
- **Particularidades técnicas:** Escalafón por antigüedad del 2% anual acumulativo sobre básico inicial (Art. 10) y adicional por zona desfavorable patagónica del 25% (Art. 13).

### 8. Actividad Aseguradora y Reaseguros (CCT 264/95)
- **Representatividad y Cobertura:** Dotación estimada en ~50.000 - 55.000 empleados en compañías de seguros y ART según estadísticas sectoriales de la Superintendencia de Seguros de la Nación (SSN) y el Sindicato del Seguro.
- **Estado de escalas:** Escalas 2026 en estado `unverified` (`importe: null`) por carecer de acta homologada en el repositorio.
- **Particularidades técnicas:** Salarios mínimos conformados por grupos y adicional por fallas de caja del 20% sobre el mínimo del Grupo I (Cláusula 10°).

### 9. Industrias de la Alimentación (CCT 244/94)
- **Representatividad y Cobertura:** Cobertura estimada por la FTIA en ~100.000 - 110.000 trabajadores de plantas de procesamiento y manufactura alimentaria; sin padrón estatal por CCT.
- **Estado de escalas:** Escalas 2026 en estado `unverified` (`importe: null`) por no contar con acta homologada en el repositorio.
- **Particularidades técnicas:** Remuneraciones mínimas conformadas (Art. 11), cláusulas de polivalencia funcional y articulación por ramas.

### 10. Seguridad y Vigilancia Privada (CCT 507/07)
- **Representatividad y Cobertura:** Cobertura estimada por CAESI y UPSRA en ~100.000 - 130.000 vigiladores y operadores de seguridad física y electrónica; sin censo estatal único.
- **Estado de escalas:** **8 escalas verificadas** (`estado: "verified"`). Respaldadas de forma directa en el anexo de la **Resolución (Sec. Trabajo) 732/2007** (pág. 15), con documento PDF oficial en el repositorio (`normative/cct/pdfs/cct_507_07.pdf`).
- **Particularidades técnicas:** Bonificación por antigüedad del 1% anual (Art. 24) y viáticos no remunerativos conforme al Art. 106 de la LCT (Art. 33).

---

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

## 6. Auditoría de Veracidad y Estado del Catálogo Salarial

A fin de garantizar que ninguna cifra sin respaldo documental oficial sea interpretada como vigente o confirmada, se realizó una auditoría integral sobre las 29 escalas del catálogo:

### Métricas de la Auditoría
- **Total de escalas salariales registradas:** 29
- **Escalas verificadas (`estado: "verified"`):** 8 (27,6%)
  - Todas correspondientes al **CCT 507/07** (Seguridad y Vigilancia Privada).
  - Fuente oficial local: [`cct_507_07.pdf`](file:///media/abp/SSD/Proyectos%20Python/Scripts/mrbot-payroll/normative/cct/pdfs/cct_507_07.pdf), Resolución (Sec. Trabajo) 732/2007, anexo salarial de la página 15. Contempla los valores en ARS para julio-septiembre de 2007 ($940, $1.034, $1.081, $1.128) y octubre de 2007 en adelante ($1.002, $1.102, $1.152, $1.202).
- **Escalas no verificadas / pendientes (`estado: "unverified"`):** 21 (72,4%)
  - **CCT 76/75 (Construcción - 4 escalas):** El documento histórico obrante en el repositorio consigna jornales diarios en Pesos Ley 18.188 ($L) diferenciados por zonas (Zona A: Oficial $260,73; Zona C: Sereno $5.105,70), no en Pesos (ARS). Las cifras 336.66 y 309.68 no surgen del texto normativo original. Las 4 escalas fueron reclasificadas a `unverified`, con `importe: null`, preservando el valor histórico en `estimated_value`.
  - **CCTs 130/75, 260/75, 18/75, 40/89, 389/04, 122/75, 264/95, 244/94 (17 escalas):** Correspondían a importes con vigencia fijada en 2026 que constituían proyecciones técnicas sin acta paritaria oficial homologada en el repositorio. Se reclasificaron con `estado: "unverified"`, `importe: null`, y su valor estimado en `estimated_value` con nota aclaratoria.

### Fuentes Oficiales Agregadas y Validadas
- **Resolución (Sec. Trabajo) 732/2007 (Anexo Salarial pág. 15):** Fuente oficial directa incorporada en `normative/cct/pdfs/cct_507_07.pdf` que respalda las 8 escalas verificadas.
- **Textos oficiales de los 10 convenios:** Disponibles en `normative/cct/pdfs/` con integridad SHA-256 contrastada.
- **Pendientes:** La incorporación de escalas 2026 verificadas requerirá la descarga formal de las respectivas actas paritarias homologadas por la Secretaría de Trabajo con su correspondiente checksum e inclusión en el repositorio.

---

## 7. Limitaciones Normativas Identificadas

1. **Dinámica Paritaria:** En Argentina las escalas de los convenios colectivos se actualizan periódicamente (mensual, bimestral o trimestralmente) mediante acuerdos celebrados en paritarias y homologados por la Secretaría de Trabajo.
2. **Sumas No Remunerativas Complejas:** Los acuerdos paritarios recientes con frecuencia incorporan asignaciones no remunerativas transitorias con aportes parciales a obras sociales o sindicatos, cuya desagregación impositiva debe modelarse a nivel de bases imponibles particulares.
3. **Dispersión de Ramas Internas:** Convenios extensos como UOM 260/75 y Camioneros 40/89 poseen decenas de ramas y anexos específicos (ej. siderurgia, transporte de caudales, combustibles). El catálogo contempla la estructura marco general y las categorías de mayor representatividad.
