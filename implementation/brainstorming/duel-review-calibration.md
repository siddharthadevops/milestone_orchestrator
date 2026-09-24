# Duel: revisión de la exigencia del evaluador

24 de septiembre de 2026. Revisión posterior al cierre. Criterio actualizado en `_impl` siguiendo las dos aclaraciones del autor: máximo de obra maestra y puntuación independiente de las críticas y preguntas. Las notas del duelo cerrado permanecen intactas.

El duelo `f404ef98-f6ca-400e-b8ff-bebe06e6e676` terminó correctamente en la ronda 3 porque ambos autores eligieron finalizar. A conservó su producción de la ronda 1; B revisó en la ronda 2. Las notas fueron A: 1; B: 0,98 → 1. Los tres dictámenes usaron `gpt-6-astra`, esfuerzo `max`, sin fallback del prompt set `literature`, según los despachos registrados en la [API de la tarea](http://127.0.0.1:8700/api/tasks/f404ef98-f6ca-400e-b8ff-bebe06e6e676).

## Diagnóstico

El problema principal es la calibración del máximo y la profundidad de su justificación. El [prompt realmente servido](/Users/siddhartha/.impl_roadmap/task-runtime/f404ef98-f6ca-400e-b8ff-bebe06e6e676/prompts/duel-review_candidate-a-1-codex-duel_review.txt:121) define 1 como cumplimiento completo sin defectos materiales encontrados. Los informes de [A](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/reports/round-001/a.md:5) y [B final](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/reports/round-002/b.md:5) dicen expresamente que su nota representa ese cumplimiento. Por tanto, las notas son coherentes con el baremo que recibieron; no equivalen a haber demostrado una ejecución literaria excelente en todo el capítulo.

La revisión literaria sí estaba pedida, tanto por el encargo como por el bloque específico de `literature`. Los informes contienen observaciones válidas sobre pérdida, deseo, conflicto y efecto lector. No sería justo reducirlos a una comprobación de archivos. Lo insuficientemente defendido es el salto de «funciona y cumple» al extremo superior de la escala.

La lectura independiente completa de ambos III confirma trabajos sólidos. No hay fundamento para asignarles ahora una nota inferior arbitraria, declarar un ganador ni exigir versiones diferentes. Sí hay evidencia útil para mejorar cómo revisamos:

### 1. Omisión documentada en la primera revisión de B

El [primer informe](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/reports/round-001/b.md:11) afirma que Hua no necesita recuerdos cuya fecha esté pendiente y solo señala el separador `***` omitido. Sin embargo, el [registro de revisión del autor](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/b/infinito-menos-uno/libro-2/trabajo/capitulo-03/informe.md:27) declara haber retirado después «Los conoces», de Versan, precisamente porque dependía de la fecha de la copia de Hua. El resumen de la ronda 2 conservado por la API confirma esa corrección.

El [acuerdo vigente sobre Hua](/Users/siddhartha/literature/infinito-menos-uno/libro-2/hua-al-servicio-de-versan.md:9) prohíbe apoyar esta escena en recuerdos que obliguen a fijar esa fecha. Es una omisión de revisión mejor sustentada que la impresión general de que 0,98 «parece demasiado». El texto final ya está corregido. No se ha recuperado una versión inicial preservada: la evidencia es el registro de corrección del autor contrastado con el dictamen inicial, no una comparación directa entre dos manuscritos históricos.

### 2. Mejora literaria local defendible en A

La seguridad de Hua se experimenta mediante su elección de silla y su posterior cambio de posición. En cambio, la amplitud mental aparece en formulaciones generales: «una idea», «una sensación» y «más» en [1828](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/a/infinito-menos-uno/libro-2/manuscrito-es.md:1828); «todo aquello» y «holgura» en [1860](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/a/infinito-menos-uno/libro-2/manuscrito-es.md:1860); otra comparación de capacidades en 1886.

Entendemos que desea conservar esa existencia, pero la nueva capacidad se vive menos que su seguridad. La [referencia de voz de IX](/Users/siddhartha/literature/infinito-menos-uno/saga/referencia-de-voz.md:573) ofrece un contraste: Pascal experimenta su ampliación en el giro de una fruta y la duración de una sílaba.

Una intervención proporcionada sería sustituir una de las afirmaciones generales por una percepción o pensamiento presente y específico de Hua, con elementos de la sala. No hace falta añadir una escena, recuerdos terrestres ni una demostración técnica. Es un juicio editorial de concreción, con confianza media; no un error de canon ni una ley universal de «mostrar en vez de contar».

El [informe A](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/reports/round-001/a.md:19) descarta como alternativas añadir garantías o cerrar el desacuerdo. Esas intervenciones perjudicarían el encargo; descartarlas no demuestra que falten mejoras locales compatibles con él.

### 3. Una precisión menor en la entrega final de B

La [nota de continuidad](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/b/infinito-menos-uno/libro-2/trabajo/capitulo-03/informe.md:13) concluye «Marco no lo acepta». En la [escena](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/b/infinito-menos-uno/libro-2/manuscrito-es.md:1779), Marco dice «Averiguar. Solo eso», Alessandro responde «Por ahora» y Marco calla. Conviene precisar el alcance de su desacuerdo para que IV no herede una oposición general a investigar. Es una ambigüedad documental pequeña, no motivo para una rebaja sustantiva ni para corregir la fricción de la escena.

### 4. Umbral de intervención demasiado grueso

[B final](/Users/siddhartha/literature/duel/f404ef98-f6ca-400e-b8ff-bebe06e6e676/reports/round-002/b.md:23) concluye que no hay beneficio que justifique «rehacer estas escenas». El primer informe también contrapone su hallazgo a una «reescritura general». Una mejora valiosa puede afectar a una réplica o un párrafo.

Oposición usa términos como premisas, garantías y alternativas materialmente mejores; la pregunta `review_reader_use` busca lo que *impide* comprender o usar. Eso puede favorecer un umbral de fallo grueso, aunque esta ejecución no demuestra por sí sola esa causalidad. El bloque literario y Dante ya permiten intervenciones pequeñas: conviene hacer explícito ese alcance en la evaluación central.

El 0,98 tampoco tiene precisión demostrada. El informe explica por qué falta una marca menor, pero no qué distingue 0,98 de 0,97 o 0,99. La puntuación no debería presentarse como un 1 inicial del que se descuentan centésimas por incidencias.

## Qué conservar

En ambos capítulos, la pérdida interrumpe el vino sin cancelar el almuerzo; el desayuno y la intimidad hacen deseable quedarse; investigar cuesta algo a Hyuna; Marco mantiene una discrepancia incómoda; la transcripción tiene trabajo real y memorizar todavía falla; Rume conserva su viaje y concede una cita concreta. Estos son efectos literarios, además de hitos cumplidos.

No propongo neutralizar la dureza de Marco, hacer razonable a todo el grupo, añadir garantías al secreto, explicar las matemáticas ni exigir más originalidad frente al rival. Tampoco considero un fallo que los informes terminen sin preguntas: Dante debe preguntar cuando haya una decisión abierta que pueda cambiar el trabajo, no para cubrir un cupo.

## Criterio actualizado

Una puntuación y el mismo informe. Se distinguen cumplimiento, juicio global de calidad, críticas y preguntas. **La puntuación es independiente de las críticas y preguntas**: no se calcula, limita ni ajusta por su número, gravedad o ausencia. No encontrar una mejora no demuestra que no exista una estructura o ejecución mejor. Encontrarla tampoco activa una deducción automática. La nota debe defenderse por el resultado logrado.

El máximo conserva las palabras exactas del autor: **«1 es obra maestra. te borrarías antes que tocar un byte de ese trabajo entregado.»** Se descarta la interpretación anterior de usar las mejoras detectadas como condición mecánica para permitir o prohibir un 1.

Párrafo común aplicado a default y literature:

```text
Assess both compliance with the request and the quality of its execution for the intended
user or reader. Distinguish those judgments in the report. The score is an independent,
overall assessment of the delivered work: its structure, coherence, execution and achieved
purpose, supported by positive evidence from the work itself.
Use these qualitative anchors on the 0-1 scale:
0: unusable or fundamentally fails the request.
0.5: a partly successful result of limited overall quality.
0.8: good, solid work.
0.9: excellent work.
The maximum has this exact definition:
1 es obra maestra. te borrarías antes que tocar un byte de ese trabajo entregado.
Full compliance or "no material defects found" alone does not justify 1. Being unable
to propose an improvement does not establish that a better structure, approach or
execution could not exist. Justify the score by the quality actually achieved, not
by the limits of your ability to criticize it.
Keep scoring independent of the criticism and anti-drift questions. Do not calculate,
cap or adjust the score from their number, severity or absence. Finding no criticism
or questions does not imply 1; raising them does not automatically lower the score.
Explain the overall quality judgment and its evidence separately from your actionable
criticism and open questions. Neither judgment substitutes for the other.
For criticism, consider proportionate local improvements as well as structural alternatives.
An improvement need not require redesigning the work or rewriting a whole scene:
identify its location, evidenced effect and proportionate benefit. If no justified
improvement is apparent, say so without manufacturing an objection or inferring perfection.
Interpolate only as the evidence warrants. These anchors are not quotas or automatic
deductions: do not start at 1 and subtract penalties, impose a distribution, or imply
precision that the evidence cannot support. Acknowledge uncertainty. Judge the requested
purpose and form without adding requirements, prescribing another style, comparing
candidates or requiring diversity.
Top-level questions support context gathering, not extra scoring dimensions.
Neither your report nor your score determines whether an author must stop.
```

Adición específica a literature:

```text
Distinguish whether a requested beat is present from how effectively the prose makes
the reader experience it. Ground judgments about rhythm, voice, tension, emotion and
clarity in passages and their surrounding context, using the supplied voice references
when relevant. A weakness may reduce an intended effect without preventing comprehension.
Explain that effect without treating taste as fact, prescribing a different style,
or neutralizing character agency and conflict. The author's delivery note is context,
not proof that the prose achieves its claims.
```

Dos preguntas de contexto actualizadas, conservando sus identificadores y sin aumentar la tanda:

- `review_better_alternative`: «Can a materially better approach or a proportionate local change improve the same requested result within its constraints? Identify the concrete benefit, or explain why the strongest plausible intervention would not help.»

- `review_reader_use`: «Read the candidate as its intended user or audience. Which specific passage or omission most weakens the requested result, even if the work remains understandable and usable? Ground the effect in evidence and distinguish it from preference. If none does, explain what supports that conclusion.»

Oposición mantiene la búsqueda de objeciones sustentadas y alternativas mejores. Dante conserva sus preguntas concretas y abiertas en `report`, sin responderlas ni disfrazar soluciones. Las respuestas a las preguntas de contexto siguen descartándose y no determinan la nota. La defensa autónoma de la puntuación, las críticas y las preguntas deben quedar distinguibles en el informe que recibe el autor.

## Alcance de los cambios

El párrafo común y las dos preguntas se aplican a `default` y `literature`; la adición literaria solo a `literature`. Las fuentes son el [seed de default](../../orchestrator/prompt_set_seed.py), su [espejo legible](prompt-router/adapted-kinds/duel/duel_review.json) y el [set literature](../../prompt_sets/literature/duel/duel_review.json). Los dos documentos persistidos activos bajo `~/.impl_roadmap/prompt_sets/` deben contener el mismo criterio: modificar solo el seed no actualizaría por sí mismo esta instalación.

El contrato JSON (`score`, `report`, `questions`), el revisor común, el paralelismo, el esfuerzo `max`, los rigores y las reglas de cierre siguen sirviendo. No hacen falta más agentes, nuevas votaciones, umbrales de parada ni campos de resultado. El criterio no reevalúa retrospectivamente las notas ni altera las trazas de la ejecución cerrada.

## Ubicación de los nuevos duelos

El directorio por defecto pasa de `<workspace>/duel/<task-id>` a `<workspace>/implementation/duel/<task-id>`, con `a/`, `b/` y `reports/` dentro. Una salida explícita conserva su ubicación elegida. Los checkpoints existentes conservan sus rutas; el primer duelo no se traslada ni pierde sus enlaces.
