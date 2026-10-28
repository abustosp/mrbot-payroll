# Verificación local de archivos del Libro de Sueldos Digital

El exportador produce un borrador; esta comprobación no presenta archivos ni verifica su aceptación por el portal de ARCA. No usa credenciales ni certifica el tratamiento fiscal, la vigencia normativa, el contenido de los conceptos o la validez de una liquidación real.

## Fuentes y alcance

El [catálogo de evidencia](../normative/lsd/catalog.json) registra las URLs oficiales y los SHA-256 de los tres PDF de diseño/detalle y los dos ZIP con las herramientas de ARCA. Las páginas oficiales son [Diseños de interfaz](https://arca.gob.ar/LibrodeSueldosDigital/ayuda/disenios.asp) y [Planillas de cálculo](https://arca.gob.ar/LibrodeSueldosDigital/ayuda/planillas-de-calculo.asp). No se incluyen los binarios en el repositorio.

La [evidencia JSON](lsd_official_evidence.json) registra fecha UTC, hashes verificados, versión de LibreOffice y las cadenas comparadas para siete casos sintéticos, uno por registro 01–06 y uno de conceptos. En la ejecución registrada, las salidas coincidieron carácter por carácter y midieron respectivamente 35, 115, 51, 370, 65, 93 y 195 caracteres. Son ejemplos puntuales, no una demostración de conformidad para todos los valores.

Las salidas de referencia están guardadas en [lsd_official_golden.json](../tests/fixtures/lsd_official_golden.json). La prueba regular compara esas salidas con los registros del exportador y con los bytes del archivo completo, incluidos los finales CRLF. También comprueba que un hash incorrecto detenga la verificación. La prueba no descarga documentos ni ejecuta LibreOffice:

```bash
uv run pytest tests/exporters/test_lsd_official_golden.py -q
```

## Reproducción con fuentes oficiales

Con `uv` y LibreOffice instalados, ejecutar desde la raíz:

```bash
uv run python scripts/verify_lsd_official.py --recalculate --report /tmp/lsd-evidence.json
```

El script descarga los cinco documentos desde las URLs fijadas, comprueba sus hashes antes de abrirlos, rellena una copia temporal de cada planilla y recalcula con LibreOffice headless en un perfil temporal aislado. Luego compara las celdas de salida con el exportador y el fixture; termina con código distinto de cero si hay diferencias. Se utiliza `Armado txt!U8` para conceptos y, para liquidaciones, `reg1!J9`, `reg2!K5`, `reg3!J5`, `reg4!AW5`, `reg5!J5` y `reg 6!E5`. Se reducen las filas de datos sobrantes en las copias temporales; se conserva `reg3!J6` para la prueba del período de ajuste. No se modifica la fórmula oficial.

Si los cinco archivos ya fueron descargados, usar `--source-dir /ruta/a/archivos` junto a las demás opciones; sus hashes se vuelven a comprobar. Sin `--recalculate`, el script verifica las fuentes y compara el exportador con el fixture, sin ejecutar las planillas. Si una fuente cambia, la verificación falla: revisar el documento y actualizar el catálogo y los casos solo tras revisar el cambio. `--write-golden` requiere `--recalculate` y guarda nuevas salidas únicamente cuando coinciden con el exportador; revisar el diff y la evidencia antes de aceptar la actualización.

## Período de ajuste del registro 03

En la planilla fijada, `reg3!J5` termina con `REPT(" ",6-LEN(I5)&I5)`. Al probar `I5 = 202605` en LibreOffice 24.2.7.2, el argumento se interpreta como `0202605` y la salida ocupa 202650 caracteres en vez de 51. El caso golden deja el período vacío y coincide. El exportador conserva el período `202605` en seis posiciones y produce 51 caracteres; no reproduce la salida defectuosa de la fórmula. Este hallazgo describe la ejecución con LibreOffice y no establece cómo Excel u otras versiones evaluarán la fórmula. La interpretación y la aceptación de un archivo real deben comprobarse mediante los controles oficiales de ARCA.
