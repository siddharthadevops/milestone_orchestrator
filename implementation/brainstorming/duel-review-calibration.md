# Duel: revisión de la exigencia del evaluador

24 de septiembre de 2026. Revisión posterior al cierre. Criterio actualizado en `_impl`: una evaluación conjunta, un informe compartido y únicamente la definición de obra maestra para el máximo; las notas son independientes de las críticas y preguntas. Las notas del duelo cerrado permanecen intactas.

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

La única definición cualitativa de la escala es la literal del autor:

> 1 es obra maestra. te borrarías antes que tocar un byte de ese trabajo entregado.

El evaluador elige libremente las demás notas dentro del formato numérico 0–1. No se prescriben bandas, etiquetas para notas inferiores, distribuciones ni descuentos por defectos. No encontrar una mejora no demuestra que no exista una estructura o ejecución mejor.

La puntuación de cada trabajo es un juicio sobre la calidad del resultado frente al encargo. Se justifica por separado de las críticas y de las preguntas de Dante. La comparación permite reconocer soluciones mejores, pero no obliga a que las notas sean distintas ni convierte a la mejor de las dos versiones en una obra maestra.

## Una evaluación y un informe para los dos autores

Después de la producción paralela, una sola llamada del revisor lee las dos versiones completas y devuelve dos notas junto con un único informe comparativo. Identifica los logros y problemas de cada trabajo y qué decisiones de uno podrían mejorar el otro, incluyendo estructura y ejecución. Oposición busca alternativas mejores y objeciones sustentadas; Dante hace preguntas concretas para evitar deriva. No se fabrican defectos ni preguntas.

Ambos autores reciben exactamente el mismo documento y las ubicaciones de las dos versiones. Se les invita a aprovechar o copiar lo que funcione en el oponente, sin imponer copia, diversidad ni una fusión final. Cada uno sigue escribiendo exclusivamente su versión y puede darla por terminada. Las dos versiones se entregan.

Mientras un autor siga trabajando, la revisión conjunta considera ambas versiones vigentes, incluida la del autor que haya finalizado; esa comparación no vuelve a activar al autor terminado. Si ambos terminan, no hay otra llamada de revisión.

## Alcance de los cambios

El contrato del revisor devuelve `scores: {a, b}`, `report` y `questions`. Las respuestas a las preguntas de contexto se descartan; las notas y el informe se conservan. Cada candidato mantiene su nota y ambos apuntan al mismo `reports/round-NNN/review.md`, también mostrado como informe compartido en el panel.

El [seed de default](../../orchestrator/prompt_set_seed.py), su [espejo legible](prompt-router/adapted-kinds/duel/duel_review.json), el [set literature](../../prompt_sets/literature/duel/duel_review.json) y los prompts de autor reflejan la revisión conjunta. Se conservan las preguntas propias de ambos sets y el enfoque literario de voz, efecto lector y continuidad. El revisor sigue siendo la primera plaza de review, Codex por defecto; todas las llamadas continúan en `max` y los tres rigores siguen seleccionando los modelos.

La actualización de los cuatro documentos persistidos de Duel bajo `~/.impl_roadmap/prompt_sets/` se realiza al activar el nuevo driver y contrato: los prompts de revisión conjunta no son compatibles con el driver anterior. La ejecución que seguía en marcha durante este cambio conserva sus prompts y sus notas; no se cambia su criterio a mitad de ronda.

## Ubicación de los nuevos duelos

El directorio por defecto sigue siendo `<workspace>/implementation/duel/<task-id>`, con `a/`, `b/` y `reports/` dentro. Una salida explícita conserva su ubicación elegida. Los checkpoints existentes conservan sus rutas; el primer duelo no se traslada ni pierde sus enlaces.
