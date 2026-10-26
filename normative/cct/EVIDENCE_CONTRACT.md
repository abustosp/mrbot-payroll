# Contrato de evidencia CCT 2020-2026

Cada worker de investigacion escribe solo su directorio
`normative/cct/evidence/<cct_slug>/`. No edita `catalog.json`, `README.md`,
`formulas.json` ni los tests globales. El merge final lo hace el coordinador o
un worker de integracion.

## Directorios asignados

- `cct_130_75`, `cct_260_75`
- `cct_76_75`, `cct_18_75`
- `cct_40_89`, `cct_389_04`
- `cct_122_75`, `cct_264_95`
- `cct_244_94`, `cct_507_07`

Cada directorio contiene:

```text
<cct_slug>/
├── sources.json
├── scales.json
├── notes.md
├── pdfs/
│   └── <archivo>.pdf
└── html/
    └── <archivo>.html
```

## sources.json

```json
{
  "cct": "130/75",
  "searched_at": "2026-10-26T19:00:00-03:00",
  "documents": [
    {
      "id": "src-001",
      "title": "Resolucion ... homologacion paritaria ...",
      "document_type": "acta_paritaria|resolucion|escala|CCT|otro",
      "authority": "Ministerio de Trabajo ...",
      "source_url": "https://...",
      "final_url": "https://...",
      "local_path": "pdfs/archivo.pdf",
      "content_type": "application/pdf",
      "http_status": 200,
      "retrieved_at": "2026-10-26T19:00:00-03:00",
      "published_at": "2025-10-01",
      "valid_from": "2025-10-01",
      "valid_to": "2025-12-31",
      "pages": 12,
      "sha256": "64 hex chars",
      "extraction": "pdftotext|pypdf|html|manual",
      "official": true,
      "notes": ""
    }
  ]
}
```

Reglas:

- `local_path` es relativo al directorio del CCT y el archivo debe existir.
- Verificar que un PDF empiece con `%PDF-` y guardar su SHA-256 real.
- Si el documento es HTML, guardar una copia y usar `content_type: text/html`.
- No aceptar un resultado de buscador como evidencia. Solo el documento oficial
  o una pagina institucional que publique el acta/escala.
- Si una fuente es secundaria, `official: false` y explicarlo en `notes`.
- Registrar tambien busquedas negativas en `notes.md`.

## scales.json

```json
{
  "cct": "130/75",
  "generated_at": "2026-10-26T19:00:00-03:00",
  "scales": [
    {
      "category_code": "ADMIN_A",
      "category_name": "Administrativo A",
      "amount": "1234567.89",
      "currency": "ARS",
      "valid_from": "2026-01-01",
      "valid_to": "2026-01-31",
      "source_id": "src-001",
      "source_page": 4,
      "source_table": "Escala salarial ...",
      "evidence_quote": "texto exacto o descripcion de la fila",
      "status": "verified|unverified",
      "confidence": "high|medium|low",
      "notes": ""
    }
  ],
  "negative_findings": [
    {
      "query": "site:argentina.gob.ar \"130/75\" escala 2025 pdf",
      "searched_at": "2026-10-26T19:00:00-03:00",
      "result": "sin resultados oficiales"
    }
  ]
}
```

Reglas:

- Solo `status: verified` si el importe y la vigencia aparecen en un documento
  oficial guardado localmente.
- No completar importes por estimacion ni por inflacion.
- Si el PDF no tiene capa de texto y no se puede leer la tabla, dejar
  `unverified` y explicar que requiere OCR/manual.
- Un mismo documento puede respaldar varias escalas; usar el mismo `source_id`.
- No duplicar filas identicas. Si hay dos escalas del mismo periodo, documentar
  la categoria o la zona.

## Cobertura temporal

Buscar documentos con fecha de publicacion o vigencia entre **2020-01-01** y
**2026-10-26**, priorizando los ultimos tres anos. Se aceptan textos base
anteriores solo como contexto, no como escala vigente.

## Reporte final

El worker debe reportar:

- documentos encontrados y descargados por CCT;
- escalas verificadas por CCT;
- fuentes oficiales usadas;
- busquedas negativas y vacios;
- cualquier CCT sin evidencia 2020-2026.

