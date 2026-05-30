# Miele MOVE pour Home Assistant

Intégration personnalisée Home Assistant pour exposer les données Miele MOVE Pro
dans des capteurs Home Assistant.

## Ce qui est récupéré

L'intégration utilise les endpoints publics documentés dans le Swagger Miele MOVE :

- `GET /api/move/v1/devices`
- `GET /api/move/v1/devices/{id}`
- `GET /api/move/v1/devices/{fabNr}/executions`
- `GET /api/move/v1/devices/{fabNr}/executions/{executionId}`

Elle crée automatiquement :

- un capteur de diagnostic `Raw data` par machine, avec les payloads complets en
  attributs ;
- des capteurs lisibles pour le programme en cours (programme, phase, temps
  restant, temps écoulé, début) ;
- des capteurs pour le dernier cycle terminé (programme, état final, durée,
  consommations d'énergie et d'eau) ;
- des capteurs d'identité de la machine (nom, modèle, état, emplacement).

Les durées (`remainingTime` / `elapsedTime`), exposées par l'API sous forme
d'objets `Duration`, sont réduites à une valeur en minutes. Les consommations
sont normalisées (Wh → kWh, ml → L). Les statuts (`RUNNING`, `completed`,
`failure`, …) sont traduits en français.

Les valeurs `null` et `-32768`, utilisées pour les champs non supportés ou sans
valeur courante, ne sont pas transformées en capteurs.

## Installation

1. Copie le dossier `custom_components/miele_move` dans le dossier
   `custom_components` de Home Assistant.
2. Redémarre Home Assistant.
3. Va dans `Paramètres > Appareils et services > Ajouter une intégration`.
4. Cherche `Miele MOVE`.
5. Renseigne ta clé API Miele MOVE.

## Clé API

La documentation Miele MOVE indique que chaque requête doit envoyer la clé via
l'en-tête `X-Api-Key`. La langue des libellés est envoyée via `Accept-Language`
et vaut `fr-FR` par défaut.

## Options

`Nombre de détails d'exécutions à récupérer` limite le nombre de requêtes de
détails d'historique par machine. La valeur par défaut est `5`, pour récupérer
les exécutions récentes sans surcharger l'API.

`Intervalle rapide (secondes)` règle la fréquence d'interrogation quand au
moins une machine est active (`running`, `programmed`, `paused`, `starting`,
`waiting_to_start`, `busy`). Par défaut `5`, minimum `3`, maximum `60`.

`Intervalle lent (secondes)` règle la fréquence d'interrogation quand toutes
les machines sont au repos (`off`, `standby`, `completed`, `error`, …). Par
défaut `120`, minimum `30`, maximum `3600`.

Le coordinator bascule automatiquement entre les deux. L'historique des cycles
(`/executions` + détails) n'est re-récupéré que lorsqu'une machine vient de
terminer un cycle ou toutes les ~10 minutes en sécurité — ça économise des
requêtes pendant les bursts rapides sans rien perdre.

## Limite d'API et rate limiting

Miele a confirmé un quota de **10 requêtes par seconde par clé API**. Avec les
défauts (5 s actif / 120 s veille), 3 machines consomment au pire ~1,2 req/s,
soit ~12 % du quota. Tu peux baisser jusqu'à 3 s sans saturer.

Si l'API renvoie un `HTTP 429 Too Many Requests`, le coordinator se met
automatiquement en back-off (au moins `slow_interval_seconds`, ou la valeur de
l'en-tête `Retry-After` si elle est plus grande) et journalise un warning.

## Migration depuis une version précédente

L'ancienne option `scan_interval_seconds` est automatiquement migrée vers
`slow_interval_seconds` à la première ouverture du formulaire d'options. La
clé legacy est ensuite supprimée.

## Notes

Cette intégration est volontairement dynamique : si Miele ajoute de nouveaux
champs à l'API ou si tes machines exposent plus d'informations, les nouveaux
champs simples apparaîtront comme nouveaux capteurs après une actualisation.
