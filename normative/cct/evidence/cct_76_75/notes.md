# Evidencia Normativa y Salarial - CCT 76/75 (UOCRA)

## 1. Resumen Ejecutivo

El Convenio Colectivo de Trabajo N° 76/75 regula las relaciones laborales del personal obrero de la industria de la construcción en todo el territorio de la República Argentina, celebrado entre la **Unión Obrera de la Construcción de la República Argentina (UOCRA)** y las cámaras patronales del sector: la **Cámara Argentina de la Construcción (CAMARCO)** y la **Federación Argentina de Entidades de la Construcción (FAEC)**.

En este repositorio de evidencia se compilaron y verificaron **29 documentos oficiales** (25 archivos PDF y 4 documentos HTML institucionales y legislativos) cubriendo el período comprendido entre el **1 de enero de 2020 y el 26 de octubre de 2026**.

Todos los archivos PDF comienzan con la cabecera `%PDF-`, cuentan con su hash criptográfico SHA-256 verificado en `sources.json`, y han sido procesados y extraídos mediante herramientas oficiales (`pdftotext`, `pdfinfo`).

---

## 2. Régimen Legal Especial: Ley 22.250 y Fondo de Cese Laboral

La industria de la construcción se rige por un estatuto laboral especial regulado por la **Ley N° 22.250**, el cual sustituye los regímenes tradicionales de preaviso y despido previstos en la Ley de Contrato de Trabajo (LCT) por el **Fondo de Cese Laboral**:

- **Artículo 15 (Ley 22.250):**
  - El Fondo se integra mediante un aporte mensual obligatorio a cargo exclusivo del empleador, depositado en una cuenta bancaria a nombre del trabajador (o en unidades UVI/UVA).
  - **Tasa 1° año de antigüedad:** **12%** de la remuneración mensual bruta devengada (básicos y adicionales convencionales).
  - **Tasa a partir del 2° año de antigüedad (mes 13 en adelante):** **8%** de la remuneración mensual bruta devengada.
  - El Art. 15 prohíbe taxativamente que estos porcentajes sean reducidos por convenio colectivo.
  - Implementación en motor de nómina: verificado y consistente con la fórmula `CCT_76_75_FONDO_CESE` en `normative/cct/formulas.json`.

---

## 3. Estructura Remunerativa Convencional

El CCT 76/75 y sus actas paritarias fijan la remuneración en base a las siguientes pautas:

### 3.1. Modalidad de Pago
- **Jornal Horario:** Para las categorías de obra:
  1. `OFICIAL_ESPECIALIZADO`: Oficial especializado en tareas específicas de alta calificación técnica.
  2. `OFICIAL`: Oficial calificado de albañilería, hormigón, carpintería, etc.
  3. `MEDIO_OFICIAL`: Medio oficial de tareas generales de construcción.
  4. `AYUDANTE`: Ayudante práctico de obra.
- **Sueldo Mensual:**
  - `SERENO`: Personal de custodia y vigilancia de obradores y materiales de obra.

### 3.2. Adicional por Asistencia Perfecta (Art. 52 CCT 76/75)
- Fija un adicional del **20% sobre el salario básico quincenal** percibido en el período, condicionado a que el operario no incurra en faltas injustificadas ni impuntualidades no autorizadas durante la quincena.
- Implementación en motor de nómina: verificado y consistente con la fórmula `CCT_76_75_ASISTENCIA` en `normative/cct/formulas.json`.

### 3.3. Zonificación Geográfica
Las escalas salariales se discriminan rigurosamente por zonas geográficas, compuestas por el Salario Básico y el Adicional Zona Desfavorable:
- **Zona A:** CABA, Provincia de Buenos Aires, Córdoba, Santa Fe, Entre Ríos, Corrientes, Misiones, Chaco, Formosa, Santiago del Estero, Tucumán, Salta, Jujuy, Catamarca, La Rioja, San Juan, Mendoza, San Luis. (Sin adicional zona: Total = Básico).
- **Zona B:** La Pampa, Neuquén, Río Negro.
- **Zona C:** Chubut, Santa Cruz.
- **Zona C-Austral:** Tierra del Fuego, Antártida e Islas del Atlántico Sur (100% adicional sobre el básico: Total = 2 × Básico).

---

## 4. Evolución Paritaria Reciente (2024 - 2026)

### 4.1. Acuerdo Vigente a Octubre 2026 (Tercer Tramo Paritario 2026-2027)
- **Acta Paritaria:** Suscripta el **21 de septiembre de 2026** por Gerardo Martínez (UOCRA), Gustavo Weiss (CAMARCO) y Ricardo Andino (FAEC). Expediente `EX-2026-92531010- -APN-CGDTEYS#MCH` (Documento GDE `RE-2026-92530721-APN-CGDTEYS#MCH`).
- **Homologación Oficial:** **Disposición DI-2026-1248-APN-DNRYRT#MCH** de fecha **29 de septiembre de 2026**, dictada por la Dirección Nacional de Relaciones y Regulaciones del Trabajo de la Secretaría de Trabajo, Empleo y Seguridad Social (Ministerio de Capital Humano).
- **Esquema de Incrementos Acumulativos:**
  - **Septiembre 2026:** 1,9% sobre básicos de agosto 2026.
  - **Octubre 2026:** 1,8% sobre básicos de septiembre 2026.
  - **Noviembre 2026:** 1,7% sobre básicos de octubre 2026.

#### Escala Testigo Vigente - Zona A (Octubre 2026):
| Categoría | Modalidad | Valor ARS |
| :--- | :--- | :--- |
| `OFICIAL_ESPECIALIZADO` | Hora | $ 7.697,00 |
| `OFICIAL` | Hora | $ 6.585,00 |
| `MEDIO_OFICIAL` | Hora | $ 6.085,00 |
| `AYUDANTE` | Hora | $ 5.601,00 |
| `SERENO` | Mensual | $ 1.017.485,00 |

#### Escala Testigo Vigente - Noviembre 2026:
| Categoría | Modalidad | Valor ARS |
| :--- | :--- | :--- |
| `OFICIAL_ESPECIALIZADO` | Hora | $ 7.828,00 |
| `OFICIAL` | Hora | $ 6.697,00 |
| `MEDIO_OFICIAL` | Hora | $ 6.188,00 |
| `AYUDANTE` | Hora | $ 5.696,00 |
| `SERENO` | Mensual | $ 1.034.783,00 |

### 4.2. Tramos Precedentes 2026
- **Segundo Tramo (Junio - Agosto 2026):** Homologado por Resolución de fecha 02/06/2026.
- **Primer Tramo (Marzo - Mayo 2026):** Acuerdo del 31 de marzo de 2026, homologado en abril de 2026. Fijó jornales horarios de Mayo 2026: Oficial Especializado $6.456, Ayudante $4.698, Sereno $853.374.

### 4.3. Cobertura Histórica 2020-2025
Se descargaron e indexaron los acuerdos y disposiciones de homologación correspondientes a:
- **2025:** Febrero, Octubre y Noviembre 2025.
- **2024:** Enero (ajuste mensual), Abril (paritaria anual) y Agosto 2024.
- **2023:** Abril (inicio ciclo 2023-2024) y Octubre 2023 (cuarto trimestre).
- **2022:** Mayo y Diciembre 2022 (reapertura paritaria).
- **2021:** Convenio y tablas salariales completas abril 2021 a febrero 2022.
- **2020:** Paritaria noviembre 2020 y homologación.

---

## 5. Búsquedas Negativas y Hallazgos

1. **Escala Unificada Nacional sin Zonas:**
   - No existe una escala única para todo el país; toda liquidación en CCT 76/75 debe identificar obligatoriamente la zona geográfica de prestación del servicio.
2. **Textos planos de anexos en Boletín Oficial:**
   - El Boletín Oficial publica los textos de resoluciones homologatorias generales pero remite a los expedientes electrónicos de la Secretaría de Trabajo (GDE) para los anexos de tablas tabuladas; la evidencia completa y digitalizada reside en las publicaciones directas de UOCRA y CAMARCO.
3. **Otros CCT del sector:**
   - UOCRA negocia también CCT 577/10 (Yacimientos petrolíferos/gasíferos), CCT 545/08 (Corralones y depósitos) y CCT 445/06 (Premoldeados). Estos fueron expresamente discriminados para asegurar que las escalas de este repositorio correspondan con exactitud a **CCT 76/75**.
