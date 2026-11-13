# Prompts para asuntos legales

`legal` adapta el flujo completo del orquestador a investigación, análisis,
redacción y revisión jurídica. Su prioridad es resolver el encargo con hechos
identificados y autoridades comprobadas, haciendo visibles las preguntas que
pueden cambiar la conclusión. No presupone jurisdicción ni convierte todos los
asuntos en litigios o dictámenes extensos.

## Comparación de los conjuntos

El análisis del 13 de noviembre de 2026 comprende los 18 documentos del seed
`default`, los 18 de `literature`, el almacenamiento, el router y los contratos
de respuesta. También se contrastaron las copias instaladas: existen diferencias
con el repositorio en planificación, checkpoints, questioner y Duel. `legal`
conserva los contratos operativos actuales del repositorio.

| Aspecto | default para código | literature | legal |
| --- | --- | --- | --- |
| Resultado | Comportamiento y contratos observables | Efecto lector y trabajo editorial solicitado | Decisión, análisis o texto jurídico solicitado |
| Evidencia | Código, consumidores, APIs y pruebas | Pasajes, contexto, continuidad y fuentes | Documentos y estado probatorio de hechos; autoridades jurídicas verificadas |
| Preguntas | Necesidad, maquinaria, confianza, coste y garantías | Voz, idiolecto, emoción, legibilidad y sorpresa | Ley y foro, fechas, posición de las partes, prueba, plazos, fuentes y contraargumentos |
| Defecto | Incumplimiento de una garantía frente al baseline permitido | Problema textual demostrable frente a una elección de gusto | Error material de hechos, Derecho, aplicación o redacción frente a una interpretación defendible |
| Proporcionalidad | Menor solución suficiente y sin mecanismos innecesarios | Menor intervención coherente sin borrar voz ni ambigüedad | Investigación y redacción suficientes para la decisión, sin quitar protecciones necesarias |
| Reutilización | Aprovechar componentes y convenciones existentes | Preservar lo establecido en el manuscrito | Comprobar que plantilla, cláusula o análisis siguen ajustándose a hechos, ley y fecha |
| Revisión Duel | Cinco dimensiones de ingeniería | Cinco dimensiones literarias | Cinco dimensiones jurídicas, con la misma media aritmética |

`literature` demuestra que un conjunto necesita una adaptación semántica
completa: cambia las bases de planificación, la evidencia, la rúbrica, la
severidad y las preguntas. Sustituir «código» por «documento» conservaría
supuestos inadecuados. En particular, ni la confianza en una maquinaria propia
ni el canon de una ficción sirven como criterio de verdad jurídica.

La jerarquía mandato, skeleton y nota determina el alcance del trabajo. La ley
aplicable y la veracidad de los hechos tienen otra fuente. Una preferencia del
cliente, una aprobación anterior o una cláusula aportada no subsanan una norma
imperativa, una cita inexistente o una conclusión sin prueba.

## Preguntas que deben cambiar el trabajo

Las preguntas se ajustan a la fase y al asunto. El agente debe leer el contexto
antes de pedirlo de nuevo, preguntar solo por lagunas materiales y continuar el
trabajo que no dependa de ellas. Las alternativas condicionales permiten avanzar
sin inventar respuestas; una incógnita decisiva impide presentar una conclusión
final como resuelta.

- ¿Qué decisión o documento se necesita, para quién y en qué condición actúa?
- ¿Qué ley, foro y territorio importan? ¿Qué fechas de hechos y de análisis, y
  qué etapa del asunto, determinan la respuesta?
- ¿Qué acredita cada documento? ¿Qué es alegación, hecho discutido, inferencia
  o supuesto? ¿Qué prueba o dato ausente puede cambiar la aplicación de la regla?
- ¿Existe una notificación, trámite o plazo material? ¿Qué hecho inicia su
  cómputo y qué regla, calendario y excepciones permiten calcularlo?
- ¿Hemos contrastado esta referencia en internet, en una fuente primaria fiable?
  ¿El artículo o párrafo realmente sostiene la proposición y se aplica aquí?
- ¿Qué autoridad, excepción o interpretación debilita nuestra posición? ¿La
  buscamos activamente, y qué nos haría cambiar de conclusión?
- ¿La entrega resuelve lo pedido con una opción o texto utilizable, y deja
  visibles las condiciones, límites y preguntas pendientes relevantes?

No se impone esta lista como intervención hablada en cada turno. Dante pregunta
solo por lo que continúa sin resolver y puede cambiar la decisión; no propone
soluciones ni adopta una tesis jurídica. La posición contraria sí contrasta
argumentos y puede proponer una alternativa respaldada por evidencia.

## Contrastación de referencias y posición jurídica

La comprobación separa tres cuestiones: que la referencia exista, que tenga la
fuerza y aplicabilidad atribuidas, y que su contenido sostenga la tesis concreta.
El texto debe leerse en contexto; los snippets, resúmenes, citas de una parte y
respuestas de IA no sustituyen esa lectura.

Se priorizan publicaciones oficiales y repositorios del legislador, tribunal,
regulador o tratado pertinente. La doctrina y otras fuentes secundarias pueden
ayudar a localizar o interpretar autoridades, pero deben identificarse y
contrastarse para apoyar conclusiones decisivas. Hay que comprobar la versión
aplicable a los hechos, entrada en vigor, reformas, derogaciones, transitorios
y tratamiento posterior relevante de las resoluciones.

Estas distinciones responden a problemas concretos. El
[BOE explica el carácter informativo de sus textos consolidados](https://www.boe.es/buscar/ayudas/legislacion_ayuda.php).
El [Ninth Circuit distingue decisiones con diferente fuerza de precedente](https://www.ca9.uscourts.gov/decisions).
La [SRA advierte sobre autoridades inventadas y confidencialidad al usar IA](https://www.sra.org.uk/solicitors/guidance/misuse-ai/).
Son fundamentos del método elegido; no convierten las reglas de una jurisdicción
en obligaciones universales.

La entrega conserva, para las proposiciones decisivas, fuente e identificador,
artículo o párrafo, enlace directo, versión o fecha aplicable, fecha de
comprobación, fuerza jurídica y límites materiales. En un instrumento que no
deba contener notas de investigación, esa información corresponde a una nota
acompañante autorizada o al informe permitido por la ruta.

El contraste busca también autoridades adversas y diferencias de hechos, foro,
jerarquía o fecha. No encontrar una autoridad contraria no prueba su inexistencia.
Puede reutilizarse una comprobación documentada para la misma proposición y
fecha de análisis, revisándola cuando cambien las fuentes, el tiempo o las dudas
relevantes. Si falla el acceso a internet o al texto completo, debe constar qué
se leyó realmente y qué conclusión sigue condicionada. Las búsquedas deben
omitir documentos confidenciales y datos que identifiquen al cliente.

## Preguntas internas y preguntas visibles

`questions.items` obliga a cada agente a examinar su trabajo. El contrato valida
identificadores y respuestas, sin determinar su calidad jurídica. Esas respuestas
no obtienen contestación del operador; en Duel se descartan expresamente.

Por eso las preguntas relevantes para el operador o los autores, las fuentes y
las incertidumbres deben figurar también en el documento, informe o `markdown`
persistente que permite la ruta. Dante debe formular las preguntas de contraste
en su intervención cuando haya una laguna material. Un autoexamen favorable
no sustituye esa intervención ni la investigación.

## Cobertura y contratos

El conjunto contiene un documento compartido, trece prompts milestone, dos de
brainstorming y dos de Duel. Se descubre por nombre sin añadir rutas ni campos
al protocolo. La orientación jurídica se monta desde el propio conjunto, incluso
cuando el material del trabajo figure como `default` o `code`.

La planificación usa una `Legal Basis` breve y unidades por resultado coherente,
sin una unidad automática por cuestión jurídica. La revisión distingue un
desacuerdo interpretativo de un defecto material y contempla riesgos futuros
como preclusión o invalidez sin exigir daño ya consumado. La revisión incremental
mantiene su límite al delta y sus efectos directos.

Duel evalúa exactamente cinco dimensiones: fuentes y vigencia; aplicación a los
hechos; contraste y manejo de incertidumbre; utilidad y proporcionalidad; claridad
y precisión. Su puntuación valora la calidad documental, no la probabilidad de
ganar. La creatividad conserva sus criterios y semánticas; las semillas no hacen
opcionales las normas ni permiten inventar hechos o autoridades. `expand_genes`
mantiene su contrato cerrado `additions`, con preguntas orientadoras internas.

`suite_checkpoint` y `merge_repair` conservan su función técnica y su batería
vacía. El checkpoint incluye el contrato actual de aplazamientos periódicos y
`not_verified`. Ninguna comprobación mecánica certifica exactitud jurídica,
vigencia de fuentes, validez o cumplimiento de plazos.

## Uso y validación

La carpeta completa debe estar en `<service-home>/prompt_sets/legal`; el home
predeterminado es `~/.impl_roadmap`. Seleccionar `legal` en el panel o en la
configuración del trabajo lo vincula al conjunto. No hace falta modificar el
router ni sustituir los conjuntos existentes. La consulta efectiva de fuentes
depende de las herramientas y el acceso disponibles para el agente ejecutor.

La prueba `orchestrator.tests.test_legal_prompt_set` carga el corpus real y
ejercita 63 combinaciones de rutas directas y 54 de sesiones: resolución sin
fallback, renderizado, enlace de contratos, herencia de preguntas y rechazo de
respuestas malformadas. Estas comprobaciones prueban integración estructural;
la calidad de una investigación jurídica exige observar sus fuentes, razonamiento
y resultado en un asunto real.
