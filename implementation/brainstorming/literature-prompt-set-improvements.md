# Informe: posibles mejoras del prompt set `literature`

Estado: **brainstorming no canónico — análisis de posibles mejoras
(2026-09-03)**. Este documento no autoriza cambios en el set instalado.

## Conclusión

`literature` ya tiene una base sólida: lee el texto antes de juzgar, separa
defecto de gusto, protege voz y ambigüedad, limita el alcance y pide evidencia
textual. No conviene añadir más listas de lentes ni crear rutas específicas
para título, voz, personajes, ritmo, etc. Eso haría el set más largo y más
mecánico sin una necesidad demostrada.

La mejora con más probabilidad de elevar la calidad es **sustituir preguntas
genéricas de autocertificación por pocas preguntas que obliguen a mostrar el
resultado literario concreto**. En particular faltan cuatro comprobaciones:

1. que la salida resuelva la decisión exacta pedida, no solo que respete el
   proceso;
2. que identifique qué funciona ya y debe conservarse;
3. que pruebe una lectura alternativa antes de declarar un defecto;
4. que preserve el idioma, variedad y alternancia de lenguas del texto.

No hay todavía base para afirmar una mejora de rendimiento real: el registro
de tareas actual no contiene ejecuciones que hayan seleccionado `literature`. Las
propuestas siguientes son hipótesis razonadas y deben probarse con casos
literarios reales antes de aceptarse.

## Evidencia revisada

- El set instalado contiene los 12 documentos canónicos y carga correctamente.
- Las 33 combinaciones de ruta actualmente disponibles ensamblan y renderizan
  sin fallback. Sus prompts van de 279 a 1.131 palabras, con una media de 748;
  son, de media, 71 palabras más breves que los equivalentes de `default`.
  La longitud global no es, por tanto, el primer problema que resolver.
- Las preguntas actuales se concentran en adecuación al entorno, escala humana,
  reutilización y ausencia de invención. Son buenas barreras contra la deriva,
  pero permiten respuestas formularias del tipo «sí, se respetó la voz».
- Una producción de nota mediante Brainstorming puede acumular seis preguntas
  obligatorias al heredar las del autor directo. Añadir más preguntas globales
  empeoraría la relación señal/ruido.
- Solo Dante recibe una regla explícita sobre el idioma de respuesta. El autor,
  revisor y corrector reciben reglas generales de voz, pero ninguna prohibición
  clara de traducir, neutralizar dialecto o borrar alternancias lingüísticas no
  pedidas.
- La crítica está orientada a hallazgos. Se ordena preservar los aciertos, pero
  ninguna pregunta obliga a localizar el efecto que ya funciona y que una
  revisión podría destruir.

## Cambio recomendado en las preguntas de salida

La regla debe ser **reemplazar, no acumular**. Cada llamada debería contestar
como máximo dos o tres preguntas distintas de su contrato principal.

| Superficie | Preguntas propuestas | Qué mejora |
| --- | --- | --- |
| Autor inicial, implementación y corrector | **`task_outcome`**: «¿Qué decisión o entrega literaria pidió exactamente el encargo y qué fragmento concreto de la salida demuestra que se resolvió con la intervención mínima?» | Evita entregar un análisis correcto pero no elegir, revisar, crear o dictaminar lo pedido. |
| Autor inicial, implementación y corrector | **`textual_fidelity`**: «¿Qué efecto valioso, rasgo de voz, hecho, ambigüedad o forma del texto corría riesgo de perderse, y qué comparación muestra que se conservó o cambió deliberadamente? Si no existía texto previo, ¿qué libertad creativa quedó abierta?» | Reduce homogeneización, sobreexplicación y falsos bloqueos en creación desde cero. |
| Revisión y delta review | **`strongest_counterreading`**: «¿Cuál es la lectura alternativa plausible más fuerte del pasaje y hace desaparecer o rebaja algún hallazgo? Explica la decisión con el texto.» | Obliga a intentar refutar el hallazgo y separa mejor defecto de preferencia. |
| Revisión y delta review | **`editorial_priority`**: «Si solo pudiera hacerse un cambio, ¿cuál alteraría más el efecto solicitado sobre el lector? Si ninguno es material, di que no cambiarías el texto.» | Produce una conclusión accionable y permite una revisión limpia sin fabricar trabajo. |
| Skeleton y nota de slice | **`downstream_decision`**: «¿Qué decisión material tendrá que tomar el próximo autor o editor, y dónde encuentra orientación suficiente sin quedar atado a una técnica o redacción?» | Prueba la utilidad real del documento para su consumidor. |
| Dante | **`question_leverage`**: «¿Qué decisión concreta podría cambiar cada pregunta que hiciste?» y **`missing_evidence`**: «¿Qué pasaje o contexto ausente justificó preguntar en vez de concluir?» | Sustituye tres autoauditorías solapadas por dos controles directos sobre la calidad de sus preguntas. |

Conviene mantener las preguntas actuales de `reclassify`: ya separan
probabilidad de desvío y coste de corrección, que son decisiones distintas. Los
checkpoints técnicos y la reparación Git tampoco necesitan preguntas
literarias añadidas.

### Preguntas por tipo de encargo, sin nuevas rutas

El prompt general debería indicar que el autor formule internamente un criterio
de éxito específico a partir del encargo. Puede ofrecer ejemplos, no una nueva
taxonomía obligatoria:

- **Títulos:** «¿Qué promesa de tono, género o tema hace cada finalista, qué
  parte del manuscrito la sostiene y cuál opción gana por encaje y recuerdo sin
  explicar demasiado?» Si se pide elegir, una lista sin elección no completa
  la tarea.
- **Voz o estilo:** «¿Qué señales observables —dicción, sintaxis, ritmo, punto
  de vista o distancia— definen la voz aquí, y qué cambia sin neutralizarlas?»
- **Personaje o continuidad:** «¿Qué sabe, quiere y puede saber el personaje en
  este punto, y qué pasaje anterior o posterior limita la revisión?»
- **Preparación editorial:** «¿Cuál es el obstáculo decisivo para enviar, si
  existe, y qué evidencia sostiene un veredicto claro de listo, no listo o
  listo con condiciones?»

Estas preguntas no deben montarse en todas las tareas. Solo deben orientar la
pregunta `task_outcome` cuando el encargo correspondiente las haga relevantes.

## Mejoras de redacción de los prompts

1. **Añadir una regla de fidelidad lingüística compartida.** Responder en el
   idioma pedido; al editar, conservar idioma, variedad, dialecto y alternancia
   de lenguas del texto; no traducir ni normalizar salvo petición expresa.
2. **Distinguir revisión de creación desde cero.** Si existe texto previo, se
   exige lectura y continuidad. Si no existe, el mandato y las fuentes son la
   autoridad; no se inventan citas ni se trata la ausencia de manuscrito como
   bloqueo. Las decisiones creativas nuevas se presentan como elecciones, no
   como hechos heredados.
3. **Pedir una conclusión cuando el encargo la exige.** Comparar opciones no
   sustituye a escoger, priorizar o emitir un veredicto.
4. **Eliminar repeticiones al cambiar preguntas.** `environment_fit`,
   `human_scale` y `machinery_trust` repiten varias veces audiencia, etapa,
   voz, invención y alcance. Sus protecciones deben conservarse en la guía,
   mientras las preguntas de salida se dedican a evidencia de resultado,
   fidelidad y decisión.

## Qué no cambiar todavía

- No crear rutas o materiales separados para cada lente literaria.
- No ampliar el esquema de salida ni construir un evaluador automático de
  calidad literaria: ninguna regla puede verificar mecánicamente esa calidad.
- No añadir terminología crítica especializada por defecto. Debe usarse solo
  cuando aclare una decisión para el autor, no como exhibición de análisis.
- No convertir «identificar un acierto» en elogio obligatorio. Solo debe
  localizar un efecto relevante que una intervención podría dañar.

## Verificación propuesta

Antes de modificar el set, guardar cuatro salidas base y repetir los mismos
encargos con la revisión candidata, manteniendo modelo, material y contexto:

1. escoger y justificar títulos;
2. revisar un pasaje de voz marcada;
3. hacer una crítica estructural;
4. dictaminar preparación para envío editorial.

Una comparación humana ciega debe valorar cinco aspectos: cumplimiento exacto
del encargo, evidencia textual, preservación de voz, utilidad de la conclusión
y fidelidad lingüística. También debe registrar verbosidad y afirmaciones sin
apoyo. Solo se adopta cada cambio si mejora esos resultados sin aumentar la
deriva ni las respuestas formularias. Este piloto usa la selección y validación
existentes; no necesita infraestructura nueva.
