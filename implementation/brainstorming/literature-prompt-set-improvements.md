# Informe: posibles mejoras del prompt set `literature`

Estado: **brainstorming no canónico — análisis de posibilidades
(2026-09-03)**. Este documento no autoriza cambios en el set instalado.

## Dictamen

`literature` ya obliga a leer el texto, separar defecto de gusto, proteger voz
y ambigüedad, limitar el alcance y aportar evidencia textual. No hay
ejecuciones registradas que hayan seleccionado este set ni una entrega
literaria fallida que permita atribuir daño a sus preguntas.

El supuesto hueco principal tampoco está demostrado: `implement` ya ordena
crear o revisar directamente el material pedido y compara la entrega con el
brief y el efecto buscado; planificación parte del mandato; revisión exige
estándar, pasaje y consecuencia material. Que ninguna pregunta diga
literalmente «escoge» no prueba que el sistema permita incumplir un encargo de
elección.

Por tanto, la respuesta proporcionada al encargo es **no cambiar ahora el set**.
Sí quedan dos hipótesis concretas para observar: cierre de la decisión pedida en
`implement` y contralectura en `review_round`/`delta_review`. Solo un caso real
debe activar una prueba, sobre la ruta que falle y sin ids nuevos.

## Qué hacen —y qué no hacen— las preguntas de salida

El contrato solo comprueba que cada id montado tenga una respuesta no vacía.
En Brainstorming, el turno siguiente y el chat compartido reciben el Markdown,
no esas respuestas estructuradas. Su consumidor posible es el propio modelo
como autoconsulta; no son por sí mismas evidencia ni una garantía de calidad.

La mejora debe juzgarse en el manuscrito, documento o Markdown final. Optimizar
la apariencia de las autoauditorías sin mejorar esa entrega sería añadir
ceremonia.

## Evidencia revisada

- Los 12 documentos canónicos cargan y sus 15 rutas directas y 18 rutas de
  sesión ensamblan sin recurrir a `default`.
- Planificación responde cuatro preguntas, implementación tres, revisión dos y
  Dante tres; una sesión productora puede heredar además las de su tarea.
- El intro de `literature` ya pide evidencia textual o editorial. Las 222
  respuestas históricas citadas pertenecen a `default` y a trabajo sobre
  código: no miden esta redacción ni una entrega literaria.
- `review_round` y `delta_review` ya exigen distinguir defecto de gusto y
  demostrar daño por encima del baseline permitido. `fix_findings` ya contiene
  una pasada explícita de falsificación que puede reutilizarse si aparece el
  problema.
- Las tres preguntas de Dante protegen cosas distintas: voz y forma, relevancia
  decisoria con fundamento, y deriva respecto del encargo. Sustituirlas perdería
  cobertura.
- No apareció otro sistema de prompts literarios en los repositorios
  concedidos que deba conectarse o extenderse.

## Hipótesis precisas por ruta

| Ruta | Cobertura actual | Señal que justificaría actuar | Cambio mínimo que probar |
| --- | --- | --- | --- |
| `implement` | Crear o revisar lo pedido directamente; contrastar la entrega con el brief y el efecto buscado. | Un encargo exige escoger, priorizar o dictaminar y la entrega real solo compara opciones. | Añadir una cláusula a su `human_scale`: «¿La entrega ejecuta el acto pedido o solo describe opciones? Señala dónde lo resuelve». |
| `review_round` | Cada hallazgo necesita estándar, pasaje, daño material y alternativa proporcionada. | Un hallazgo de gusto sobrevive porque el revisor no probó una lectura plausible del pasaje. | Añadir la contralectura al `human_scale` de esta ruta, reutilizando la falsificación ya usada por el fixer. |
| `delta_review` | Igual que revisión, pero limitado al cambio y sus efectos directos. | El mismo fallo aparece específicamente al revisar un delta. | Aplicar allí la misma cláusula; no tocar la revisión completa por anticipado. |
| `draft_skeleton`, `draft_slice_note`, `reclassify`, `fix_findings` | Sus preguntas homónimas gobiernan planificación, tamaño, rating o resolución de una cola. | Ninguna señal actual. | Ningún cambio: no extender a ellas una recomendación por compartir id. |
| Dante | Tres controles complementarios sobre adecuación, preguntas decisorias y foco. | Ninguna señal actual. | Mantener `turn_environment_fit`, `turn_human_scale` y `request_focus`. |

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

Las primeras ejecuciones reales de `literature` deben conservar el encargo, la
ruta y la entrega final. Si aparece uno de los fallos anteriores, se compara el
prompt actual con **una sola cláusula candidata**, manteniendo iguales modelo,
texto y contexto. La persona que pidió el trabajo valora si la entrega resolvió
el acto exacto, fundamentó sus afirmaciones y conservó el efecto o la voz que
debía permanecer.

No hace falta ahora un piloto ciego, un evaluador ni una métrica de respuestas
estructuradas. Solo se conserva un cambio si mejora la entrega sin añadir
verbosidad, hallazgos de gusto o trabajo ajeno al encargo.

## Fuera de alcance

- No modificar el set instalado ni crear rutas o baterías nuevas.
- No almacenar autoauditorías como una nueva autoridad.
- No presentar el corpus de `default` como validación literaria.
- No convertir posibilidades de este informe en requisitos sin una ejecución
  afectada.
