# Informe: posibles mejoras del prompt set `literature`

Estado: **brainstorming no canónico — análisis de posibilidades
(2026-09-03)**. Este documento no autoriza cambios en el set instalado.

## Dictamen

El operador ya ha definido «rendir mejor»: las preguntas deben ampliar el
contexto considerado, reducir el literalismo y aportar sentido común. Su
consumidor es el propio agente durante el turno y la persona afectada es quien
recibe una entrega demasiado literal. Que las respuestas estructuradas no se
reutilicen después no vuelve ceremonial esa función.

`literature` ya obliga a leer el texto, separar defecto de gusto, proteger voz
y ambigüedad, limitar el alcance y aportar evidencia textual. Sus nueve
preguntas `human_scale` conservan alguna barrera de proporcionalidad adaptada a
la ruta: grano y tamaño, cambio mínimo, efecto directo, coste real o rechazo de
una auditoría exhaustiva. Por eso la ausencia de las palabras de `default` no
demuestra por sí sola una regresión funcional.

Sí aparece una mejora plausible y acotada: `review_round.human_scale` repite
controles que ya impone la rúbrica montada y dedica su respuesta a explicar
cómo se comprobó el conjunto, en vez de a **comparar la intención humana, los
hallazgos y la sobreactuación literal que se descartó**. Probar esa sustitución
no requiere ids, rutas ni baterías nuevas, y este informe no modifica el set
instalado.

## Qué hacen —y qué no hacen— las preguntas de salida

La arquitectura las diseñó como trabajo cognitivo obligatorio: describir
fuerza a comprobar y responder fuerza a decidir. La validación mecánica solo
comprueba ids y respuestas no vacías porque no puede juzgar sentido común; ese
límite de verificación no reduce la pregunta a transporte de datos.

Por tanto hay dos resultados que observar: que la respuesta muestre una
comparación real, y que esa ampliación mejore el manuscrito, documento o
Markdown final. Una respuesta más larga o con las palabras esperadas no basta.

## Evidencia revisada

- Los 12 documentos canónicos cargan y sus 15 rutas directas y 18 rutas de
  sesión ensamblan sin recurrir a `default`.
- Planificación responde cuatro preguntas, implementación tres, revisión dos y
  Dante tres; una sesión productora puede heredar además las de su tarea.
  `standalone@*` no hereda preguntas y su autor responde solo las dos del turno,
  igual que en `default`; su rol ya ordena realizar el trabajo y no hay una
  entrega fallida que convierta esa delgadez en defecto.
- El intro de `literature` ya pide evidencia textual o editorial. Las 222
  respuestas históricas citadas pertenecen a `default` y a trabajo sobre
  código: no miden esta redacción ni una entrega literaria.
- En las 24 preguntas principales, `default` usa un ejemplo trabajado en 20 y
  `literature` en ninguna; las nueve `human_scale` de `default` nombran el
  literalismo y las nueve de `literature` no. Es una diferencia de redacción,
  no una medida de rendimiento. La comparación útil es semántica: varias
  sustituciones literarias ya expresan el mismo freno con «cambio mínimo»,
  «grano y tamaño» o «auditoría exhaustiva».
- `default` es el corpus semilla y el fallback revisado, pero un set nombrado
  es un corpus completo e independiente: no existe herencia que convierta cada
  frase de `default` en obligatoria. Sirve como comparador y fuente reutilizable,
  no como canon léxico para `literature`. El acuerdo que creó el set permitía
  conservar los ejemplos genéricos de proporcionalidad que ya funcionaran a
  escala de manuscrito; reutilizar uno respeta esa autorización, no la amplía.
- `review_round` y `delta_review` ya exigen distinguir defecto de gusto y
  demostrar daño por encima del baseline permitido. `fix_findings` ya contiene
  una pasada explícita de falsificación que puede reutilizarse si aparece el
  problema.
- Las tres preguntas de Dante protegen cosas distintas: voz y forma, relevancia
  decisoria con cinco posibles fundamentos, y deriva respecto del encargo. No
  hay una señal que justifique eliminar, fusionar o estrechar ninguna.
- No apareció otro sistema de prompts literarios en los repositorios
  concedidos que deba conectarse o extenderse.

## Cambio de preguntas con mejor fundamento

No se propone restaurar transversalmente tres expresiones por conteo. Se
conserva el vocabulario literario donde ya provoca la comparación correcta, en
especial en `discussion_turn`, `draft_skeleton`, `draft_slice_note`,
`implement`, `delta_review`, `fix_findings` y `reclassify`.

| Superficie | Limitación posible | Sustitución que probar |
| --- | --- | --- |
| `review_round.human_scale` | Su cuerpo repite obligaciones de `judgment_rubric`, montada en la misma ruta: estándar, pasaje, consecuencia material, alternativa proporcionada y alcance. Lo distintivo que podría aportar la autoauditoría es la perspectiva de quien encargó la revisión. | «Pon los hallazgos junto al encargo y al manuscrito: ¿reconocería quien pidió la revisión el grano y las prioridades buscadas, o una aplicación literal de una lente convirtió variaciones inocuas en trabajo? Responde con un pasaje localizado, la consecuencia material y cualquier exceso retirado.» |

Esta es la única sustitución concreta recomendada. El ejemplo de los saltos
temporales de `default` también puede reutilizarse si la formulación abstracta
no basta; copiarlo en las nueve rutas antes de probar una sola no aportaría
nueve funciones distintas.

Que `review_round`, `delta_review` y `fix_findings` compartan la cola «explica
cómo comprobaste» no demuestra que las tres preguntas hagan el mismo trabajo.
En las dos últimas, el cuerpo conserva obligaciones propias sobre el delta o la
cola completa, y el prompt ya las enfrenta al mandato, al contexto y al efecto
lector. Sin respuestas que muestren autocertificación en esas rutas, la cola es
una observación para vigilar, no fundamento para tres cambios.

## Otras hipótesis y criterio para localizar la ruta

| Superficie | Cobertura actual | Señal que justificaría actuar | Cambio mínimo que probar |
| --- | --- | --- | --- |
| Entrega de autor (`standalone@*` o `implement`) | Ambos ordenan realizar el trabajo; `implement` además contrasta la entrega con el brief y el efecto buscado. | Un encargo exige escoger, priorizar o dictaminar y la entrega real solo compara opciones. | Probar «¿La entrega ejecuta el acto pedido o solo describe opciones? Señala dónde lo resuelve» únicamente sobre la entrega afectada; decidir el montaje después de localizar el caso. |
| `review_round` | Cada hallazgo necesita estándar, pasaje, daño material y alternativa proporcionada. | Un hallazgo de gusto sobrevive porque el revisor no probó una lectura plausible del pasaje. | Añadir la contralectura al `human_scale` de esta ruta, reutilizando la falsificación ya usada por el fixer. |
| `delta_review` | Igual que revisión, pero limitado al cambio y sus efectos directos. | El mismo fallo aparece específicamente al revisar un delta. | Aplicar allí la misma cláusula; no tocar la revisión completa por anticipado. |
| `draft_skeleton`, `draft_slice_note`, `reclassify`, `fix_findings` | Sus preguntas homónimas gobiernan planificación, tamaño, rating o resolución de una cola. | Ninguna señal actual. | Ningún cambio: no extender a ellas una recomendación por compartir id. |
| Dante | Tres controles complementarios sobre adecuación, preguntas decisorias y foco. | Ninguna señal actual. | Mantener `turn_environment_fit`, `turn_human_scale` y `request_focus`. |

La tabla localiza solo esas dos hipótesis; no inventaría todas las rutas.
Incluir `standalone@*` en la primera fila evita prejuzgar dónde estaría un
fallo futuro, no convierte su batería de dos preguntas en una carencia. Sus
preguntas de turno son compartidas y no permiten aislarla; resolver esa
topología sin un fallo localizado seguiría siendo maquinaria innecesaria. Esa
restricción no aplica a mejorar la función transversal de `human_scale`, cuyo
usuario y propósito el operador ya ha identificado.

La contralectura no debe colgar de `environment_fit`: esa pregunta preserva
audiencia, etapa, voz, ambigüedad y forma frente a la convencionalización. El
objeto que se intenta refutar es el hallazgo, ya gobernado por `human_scale`.

## Otras posibilidades, aún sin caso

- **Creación desde cero.** `implement` ya dice «crear o revisar». Solo si una
  ejecución se bloquea por no haber manuscrito previo tendría sentido aclarar
  en esa ruta que el mandato y las fuentes disponibles son la autoridad.
- **Fidelidad lingüística.** Voz y dicción ya están protegidas, y Dante sigue el
  idioma del encargo. Solo una traducción o neutralización no pedida de variedad,
  dialecto o alternancia de lenguas justificaría reforzar esa regla.
- **Conclusión pedida.** Antes de tocar una pregunta, debe existir una entrega
  que incumpla el acto solicitado pese a las instrucciones actuales. Sin ella,
  `task_outcome` sería una segunda formulación del contrato, no una solución.

No se recomiendan `textual_fidelity`, `editorial_priority`,
`downstream_decision`, `question_leverage` ni `missing_evidence` como ids
nuevos: sus objetivos ya están cubiertos o no tienen víctima demostrada.

## Validación proporcionada

En una primera revisión literaria real, se puede comparar la pregunta actual
con **solo la sustitución de `review_round`**, manteniendo iguales modelo, texto
y contexto. Se conservan tanto la autoauditoría como la entrega. La persona que
pidió el trabajo valora si el agente reconstruyó mejor su intención, retiró
trabajo nacido de una lectura literal y mantuvo los hallazgos materiales.

No hace falta un evaluador ni una métrica léxica. Solo se conserva el cambio si
mejora la entrega sin añadir verbosidad, hallazgos de gusto o trabajo ajeno al
encargo.

## Fuera de alcance

- No modificar el set instalado ni crear rutas o baterías nuevas.
- No almacenar autoauditorías como una nueva autoridad.
- No presentar el corpus de `default` como validación literaria.
- No convertir la redacción exacta de `default` en requisito de todos los sets.
