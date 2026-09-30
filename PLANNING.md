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
- [x] `k_shortest_paths` : plusieurs chemins distincts en excluant une connexion du meilleur chemin trouvé à chaque itération (pas un vrai algo de Yen, mais suffisant pour easy/medium)
### Soir
- [ ] Tests rapides pathfinding (zone bloquée, chemin coûteux, aucun chemin possible) — validé à la main en session interactive, **pas encore en pytest**
- [x] **Jalon :** pathfinding validé sur toutes les maps easy/medium — étendu de fait à hard/challenger aussi (10/10 maps donnent un chemin)

> Note : A\* a été choisi à la place d'un Dijkstra/BFS écrit à la main. C'est un Dijkstra guidé par une heuristique admissible (donc toujours optimal), pas une régression — à mentionner tel quel à l'oral si demandé.

## Jeudi 10/09
### Matin
- [x] `simulation.py` : chaque drone, l'un après l'autre, prend l'horaire le plus tôt sur l'un des k chemins candidats, en évitant les places (zone, tour) / (lien, tour) déjà réservées ; restricted = 2 tours (lien utilisé au départ seulement, place vérifiée à l'arrivée)
### Après-midi
- [x] Gestion des deadlocks/collisions, ordre de priorité entre drones — impossible par construction : on respecte les réservations des drones précédents, et un drone peut toujours attendre dans start
- [x] `src/__main__.py` : point d'entrée unique (`make run`) → `render.run_gui()` ; `main.py` et `make render` supprimés
### Soir
- [x] Brancher la simulation dans `render.py` (remplacer `parse_map_file`/`Zone` locaux par le vrai `Graph` pydantic) — les tours sont affichés dans le terminal, une erreur de map est affichée et ramène au menu
- [x] **Jalon :** simulation correcte sur toutes les maps, capacités respectées (vérifié par un rejoueur indépendant) — optimum du sujet atteint partout : 4/4/4, 8/10/6, 13/16/26, challenger 43

## Vendredi 11/09 — jour de deadline
### Matin
- [x] Animation graphique des drones (potato.png, un tour par seconde) ; zones dans leur couleur de la map (pas de feedback spécifique blocked/priority/restricted)
### Après-midi
- [ ] Refactor de `render.py` en modules séparés si le temps le permet (sinon reporté après la deadline)
- [ ] `flake8` + `mypy --strict` clean sur tout le projet
- [ ] Tests pytest sur les cas limites (zone bloquée, capacité dépassée, map malformée, aucun chemin)
### Fin de journée (buffer 17h–19h)
- [ ] `make install/run/debug/clean/lint/lint-strict/test` vérifiés sur un clone propre
- [ ] `.gitignore` / README à jour, commit propre
- [ ] **Deadline finale : projet fonctionnel et lintable, prêt pour la peer review, ~19h**
