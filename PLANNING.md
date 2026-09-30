# Fly-in — Planning (deadline : vendredi 11/09 soir)

## Décisions prises
- [x] Modèles : **pydantic uniquement**, parsing ET objets du domaine (pas de dataclasses séparées), pour rester homogène
- [x] `render.py` = seule base considérée comme acquise (menu + sélection map) ; le reste (`parser.py`, `pydantic_models.py`, `src/models/*.py`) est repris depuis zéro

## Mardi 8/09 — soir (Parser + modèles)
- [x] Fusionner `src/models/*.py` dans `pydantic_models.py` : un seul jeu de classes `Zone`, `Connection`, `Graph`, `Drone` en `BaseModel`
- [x] `zone_type` en `Literal` + coût de déplacement associé (normal=1, priority=1, restricted=2, blocked=infranchissable)
- [x] Réécrire `parser.py` sur le vrai format du sujet (`nb_drones:`, `start_hub:`/`end_hub:`/`hub:`, `connection: a-b [max_link_capacity=2]`, métadonnées entre crochets, commentaires `#`) — `parse_map_file(filepath) -> Graph`
- [x] Gestion d'erreurs : nom dupliqué / start-end manquant ou multiple / connexion vers zone inconnue / doublons — portée en grande partie par la validation pydantic de `Graph` (`check_consistency`, `zones_from_list`), le reste (nb_drones/start/end manquant ou dupliqué) vérifié explicitement dans `parse_map_file`
- [x] **Jalon :** les 10 maps fournies (3 easy/3 medium/3 hard/1 challenger — le planning disait "9" par erreur) se parsent sans erreur — vérifié aussi que `PathFinder.a_star` trouve un chemin sur les 10, y compris "the_impossible_dream"

## Mercredi 9/09
### Matin
- [x] Finaliser les modèles domaine (docstrings, méthodes `get_neighbors` / `get_connection` sur `Graph`) — `__repr__` custom jugé inutile, celui de pydantic suffit
- [x] Ajout du modèle `Path` (zones, total_cost) dans `pydantic_models.py`
- [ ] `utils.py` : reporté — les coûts de déplacement vivent déjà dans `Zone.move_cost` / `ZONE_MOVE_COST`, pas de helpers communs identifiés pour l'instant
### Après-midi
- [x] `pathfinding.py` : `PathFinder.a_star` (A\* avec heapq, heuristique euclidienne admissible mise à l'échelle via `_min_cost_per_distance`), tient compte des coûts de zone, remplace le Dijkstra/BFS prévu initialement (voir note ci-dessous)
- [x] `k_shortest_paths` : k plus courts chemins exacts, par ordre de coût — chaque chemin trouvé engendre un candidat par connexion exclue (variante simplifiée de Yen). L'ancienne version (exclusion de la 1re connexion seulement) ne trouvait qu'un chemin sur simple_fork, maze_nightmare et le challenger
### Soir
- [ ] Tests rapides pathfinding (zone bloquée, chemin coûteux, aucun chemin possible) — validé à la main en session interactive, **pas encore en pytest**
- [x] **Jalon :** pathfinding validé sur toutes les maps easy/medium — étendu de fait à hard/challenger aussi (10/10 maps donnent un chemin)

> Note : A\* a été choisi à la place d'un Dijkstra/BFS écrit à la main. C'est un Dijkstra guidé par une heuristique admissible (donc toujours optimal), pas une régression — à mentionner tel quel à l'oral si demandé.

## Jeudi 10/09
### Matin
- [x] `simulation.py` : moteur tour par tour multi-drones, capacités zone (`max_drones`) et connexion (`max_link_capacity`), zone restricted = 2 tours (connexion occupée 2 tours, place réservée à l'arrivée), répartition des drones sur les k chemins selon coût + charge / débit du goulot
### Après-midi
- [x] Gestion des deadlocks/collisions, ordre de priorité entre drones — drones les plus avancés d'abord, tour résolu en passes jusqu'à stabilité (une place libérée sert dans le même tour), `DeadlockError` si un tour passe sans aucun mouvement (détection, pas de résolution)
- [x] `src/__main__.py` : point d'entrée (`make run`) menu → parse → simulate → render ; `python -m src <map>` = mode terminal (une ligne par tour). `main.py` à la racine reste le template uv, à supprimer ?
### Soir
- [x] Brancher la simulation dans `render.py` (remplacer `parse_map_file`/`Zone` locaux par le vrai `Graph` pydantic)
- [x] **Jalon :** simulation correcte sur toutes les maps, capacités respectées — vérifié par un rejoueur indépendant (capacités zone/lien à chaque tour, connexions existantes, 2 tours en restricted). Tours : easy 4/4/4, medium 8/15/7, hard 13/16/27, challenger 47 (référence : 45)

## Vendredi 11/09 — jour de deadline
### Matin
- [x] Animation graphique des drones (potato.png, interpolation entre tours, SPACE/←/→/↑/↓/R) + feedback visuel zones bloquées/priority/restricted, occupation n/max, épaisseur des liens selon capacité, échelle adaptée à l'écran
### Après-midi
- [ ] Refactor de `render.py` en modules séparés si le temps le permet (sinon reporté après la deadline)
- [ ] `flake8` + `mypy --strict` clean sur tout le projet
- [ ] Tests pytest sur les cas limites (zone bloquée, capacité dépassée, map malformée, aucun chemin)
### Fin de journée (buffer 17h–19h)
- [ ] `make install/run/debug/clean/lint/lint-strict/test` vérifiés sur un clone propre
- [ ] `.gitignore` / README à jour, commit propre
- [ ] **Deadline finale : projet fonctionnel et lintable, prêt pour la peer review, ~19h**
