# Brainstorming con control de drift

## Objetivo

Evitar que todos los participantes acepten la premisa inicial y colaboren en
perfeccionar una solución equivocada.

## Participantes

- **Árbitro:** observa la conversación, no defiende ninguna postura y fija la
  conclusión final. Solo él modifica el target al cerrar.
- **Posición inicial:** presenta y defiende la propuesta inicial.
- **Posición contraria:** una IA de la familia opuesta construye el mejor caso
  posible contra la premisa, contrastándola con el objetivo y las decisiones
  existentes.
- **Dante:** no adopta postura ni propone soluciones. En cada ronda formula
  preguntas sencillas que puedan descubrir drift. Los otros participantes
  deben responderlas en la ronda siguiente.

## Ronda

1. Interviene la posición inicial.
2. Interviene la posición contraria.
3. Dante formula sus preguntas anti-drift.

El request debe describir neutralmente el objetivo que hay que resolver, nunca
ordenar de antemano la solución deseada.

## Cierre del árbitro

- **Objective achieved:** existe una conclusión utilizable. Puede consistir en
  no cambiar nada o en declarar incorrecta la propuesta inicial.
- **Objective not achieved:** el resultado solicitado no debe o no puede
  realizarse dentro de los límites existentes, sin que falte información.
- **Gap:** falta una decisión, dato, autoridad o capacidad externa concreta y
  no puede alcanzarse una conclusión responsable.

Rechazar la posición inicial no implica que el brainstorming haya fracasado.
Si el objetivo era decidir si hacía falta un amendment, concluir que no hace
falta es **Objective achieved**.
