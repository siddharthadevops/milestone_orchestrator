# Informe: posibles mejoras del prompt set `literature`

Estado: **brainstorming no canónico — análisis de posibles mejoras
(2026-09-03)**. Este documento no autoriza cambios en el set instalado.

## Dictamen

`literature` ya tiene una base sólida: obliga a leer el texto, separa defecto
de gusto, protege voz y ambigüedad, limita el alcance y pide evidencia
textual. No hay ejecuciones registradas que hayan seleccionado este set, así
que hoy no existe evidencia de un fallo de rendimiento literario ni base para
declarar que una redacción nueva rendirá mejor.

El encargo pide un informe de posibilidades, no elegir ni desplegar un
rediseño. La dirección más proporcionada es **afinar preguntas e instrucciones
existentes sin aumentar su número**. En concreto, merece probarse que el autor
demuestre el resultado pedido y que el revisor intente una lectura alternativa.
La fidelidad lingüística y la creación desde cero pueden aclararse con una
línea cada una dentro de reglas ya montadas. No hacen falta rutas, unidades,
campos de salida ni evaluadores nuevos.

## Qué hacen —y qué no hacen— las preguntas de salida

Las preguntas son una autoconsulta obligatoria: el contrato comprueba que
cada id montado tenga una respuesta no vacía. En Brainstorming, sin embargo,
la siguiente intervención y el chat compartido reciben el Markdown, no esas
respuestas estructuradas. Estas pueden ayudar al modelo a revisar su trabajo
antes de entregarlo, pero no son por sí mismas información consumida por el
siguiente participante ni una prueba de calidad.

Por tanto, una mejora debe juzgarse por el manuscrito, documento o Markdown
final. La tasa de respuestas con anclaje solo es un diagnóstico secundario;
optimizarla sin mejorar la entrega engordaría la autocertificación.

## Evidencia revisada

- Los 12 documentos canónicos de `literature` cargan y sus 15 rutas directas
  y 18 rutas de sesión ensamblan sin recurrir a `default`.
- El set no presenta una crisis general de longitud frente a `default`. El
  riesgo local está en la batería: planificación ya responde cuatro preguntas,
  implementación tres, revisión dos y Dante tres; el autor de una sesión de
  producción hereda además las preguntas de su tarea.
- Las preguntas literarias actuales ya piden pasajes, estándares o una
  comparación concreta en la mayoría de superficies. No está demostrado que
  les falte una obligación general de anclaje.
- Ninguna pregunta comprueba explícitamente que la entrega haya tomado la
  decisión pedida. Las instrucciones tampoco aclaran que comparar opciones no
  basta cuando el encargo exige escoger, priorizar o dictaminar.
- La rúbrica de revisión separa defecto y gusto, pero no exige formular la
  lectura alternativa más fuerte antes de mantener un hallazgo.
- La protección de dicción, voz, ambigüedad, ritmo y forma ya cubre buena parte
  de la fidelidad. Solo Dante tiene una regla explícita de idioma; además,
  algunas instrucciones dicen a la vez «crear o revisar» y presuponen un
  manuscrito previo.
- Las tres preguntas actuales de Dante no son equivalentes: una protege voz y
  forma, otra exige relevancia decisoria y fundamento, y otra detecta deriva.
  Sustituirlas perdería cobertura.
- Las 222 respuestas históricas citadas en la discusión pertenecen a `default`
  y a trabajos sobre código, con preguntas distintas. Muestran que una
  autoconsulta puede contestarse de forma formularia, pero no permiten decidir
  una modificación de `literature` ni medir calidad literaria.
- No apareció otro sistema de prompts literarios en los repositorios concedidos.
  Las mejoras candidatas deben reutilizar las preguntas y reglas compartidas
  que ya existen.

## Preguntas de salida candidatas

### 1. Autor: incorporar resultado a `human_scale`

No añadir `task_outcome` ni sustituir el control específico de cada superficie.
Anteponer a la pregunta `human_scale` existente esta cláusula:

> ¿Qué resultado o decisión pidió exactamente el encargo y qué parte concreta
> de la entrega demuestra que se resolvió?

Después se mantiene la comparación actual sobre grano, tamaño, intervención
mínima y trabajo adyacente. Así se añade el único hueco claro sin perder
cobertura ni pasar de tres a cinco preguntas en implementación o de seis a más
preguntas en una sesión productora.

### 2. Revisión: probar una lectura alternativa dentro de la pregunta actual

No añadir `strongest_counterreading`. Si casos literarios reales muestran
hallazgos que confunden gusto y defecto, añadir al final de
`environment_fit`:

> ¿Qué lectura alternativa plausible del pasaje probaste y por qué no elimina
> o rebaja el hallazgo?

La cláusula conserva audiencia, género, forma y etapa editorial, y hace
observable el intento de refutación sin crear otra respuesta obligatoria.

### 3. Dante: mantener las tres preguntas

`turn_environment_fit`, `turn_human_scale` y `request_focus` deben permanecer.
La segunda ya exige preguntas capaces de cambiar la decisión y fundadas en un
pasaje, fuente, continuidad, proporcionalidad o contexto ausente. Separar
`question_leverage` y `missing_evidence` duplicaría esa función y borraría las
guardas de voz y deriva.

No se recomienda añadir `textual_fidelity`, `editorial_priority` ni
`downstream_decision`: sus objetivos ya están repartidos entre fidelidad,
rúbrica de juicio, altitud editorial y resultado pedido. Convertirlos en ids
independientes aumentaría la batería sin un consumidor o fallo demostrado.

## Mejoras candidatas en las instrucciones

1. **Conclusión pedida.** Añadir a la instrucción existente del autor: «Si el
   encargo exige escoger, priorizar o dictaminar, comparar opciones no completa
   la entrega».
2. **Creación desde cero.** Añadir a la regla de lectura y reutilización: «Si
   no existe texto previo porque el encargo es creativo, el mandato y las
   fuentes disponibles son la autoridad; no inventes citas ni trates esa
   ausencia como bloqueo».
3. **Fidelidad lingüística, solo si aparece el caso.** Reutilizar la regla de
   Dante sobre seguir el idioma del encargo y precisar en la regla de fidelidad
   que no se traduzcan ni neutralicen variedad, dialecto o alternancia de
   lenguas sin petición expresa. La protección actual de voz y dicción hace de
   esto una aclaración, no una nueva garantía.
4. **Contralectura.** Si se adopta la cláusula de revisión, reflejarla en la
   rúbrica existente; no crear una unidad paralela.

## Validación proporcionada

No hace falta lanzar ahora un piloto ciego de ocho ejecuciones ni construir un
evaluador. Cuando existan dos o más encargos literarios representativos,
comparar el prompt actual con **un solo cambio cada vez**, manteniendo iguales
modelo, texto y contexto. La persona que pidió el trabajo debe valorar la
entrega final en tres aspectos: resolvió la decisión exacta, fundamentó sus
afirmaciones en el texto y conservó el efecto o la voz que debía permanecer.

La presencia de anclajes en las respuestas estructuradas puede registrarse,
pero no decide la adopción. Solo se conserva un cambio si mejora la entrega sin
añadir verbosidad, hallazgos de gusto o trabajo ajeno al encargo. Hasta entonces,
las propuestas anteriores siguen siendo hipótesis y el set instalado no cambia.

## Fuera de alcance

- No crear rutas por título, voz, personaje, continuidad, ritmo o preparación
  editorial.
- No ampliar el esquema de salida ni almacenar las autoauditorías como nueva
  autoridad.
- No modificar ahora las preguntas de Dante ni las baterías de planificación.
- No presentar el corpus de código de `default` como validación literaria.
