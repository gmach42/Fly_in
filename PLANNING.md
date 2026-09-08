# Fly-in — Planning (deadline : vendredi 11/09 soir)

## Décisions prises
- [x] Modèles : **pydantic uniquement**, parsing ET objets du domaine (pas de dataclasses séparées), pour rester homogène
- [x] `render.py` = seule base considérée comme acquise (menu + sélection map) ; le reste (`parser.py`, `pydantic_models.py`, `src/models/*.py`) est repris depuis zéro

## Mardi 8/09 — soir (Parser + modèles)
- [x] Fusionner `src/models/*.py` dans `pydantic_models.py` : un seul jeu de classes `Zone`, `Connection`, `Graph`, `Drone` en `BaseModel`
- [x] `zone_type` en `Literal` + coût de déplacement associé (normal=1, priority=1, restricted=2, blocked=infranchissable)
- [ ] Réécrire `parser.py` sur le vrai format du sujet (`nb_drones:`, `start_hub:`/`end_hub:`/`hub:`, `connection: a-b [max_link_capacity=2]`, métadonnées entre crochets, commentaires `#`)
- [ ] Gestion d'erreurs : nom dupliqué, start/end manquant ou multiple, connexion vers zone inconnue, doublons
- [ ] **Jalon :** les 9 maps fournies se parsent sans erreur

## Mercredi 9/09
### Matin
- [ ] Finaliser les modèles domaine (docstrings, `__repr__`, méthodes `get_neighbors` / `get_connection` sur `Graph`)
- [ ] `utils.py` : coûts de déplacement, helpers communs
### Après-midi
- [ ] `pathfinding.py` : algo maison (Dijkstra/BFS écrit à la main), tient compte des coûts de zone, capable de proposer plusieurs chemins
### Soir
- [ ] Tests rapides pathfinding (zone bloquée, chemin coûteux, aucun chemin possible)
- [ ] **Jalon :** pathfinding validé sur toutes les maps easy/medium

## Jeudi 10/09
### Matin
- [ ] `simulation.py` : moteur tour par tour multi-drones, capacités zone (`max_drones`) et connexion (`max_link_capacity`)
### Après-midi
- [ ] Gestion des deadlocks/collisions, ordre de priorité entre drones
- [ ] `main.py` / `src/__main__.py` : point d'entrée unique (`make run`) qui enchaîne menu → parse → simulate → render
### Soir
- [ ] Brancher la simulation dans `render.py` (remplacer `parse_map_file`/`Zone` locaux par le vrai `Graph` pydantic)
- [ ] **Jalon :** simulation correcte en mode debug sur toutes les maps, capacités respectées

## Vendredi 11/09 — jour de deadline
### Matin
- [ ] Animation graphique des drones + feedback visuel zones bloquées/priority/restricted
### Après-midi
- [ ] Refactor de `render.py` en modules séparés si le temps le permet (sinon reporté après la deadline)
- [ ] `flake8` + `mypy --strict` clean sur tout le projet
- [ ] Tests pytest sur les cas limites (zone bloquée, capacité dépassée, map malformée, aucun chemin)
### Fin de journée (buffer 17h–19h)
- [ ] `make install/run/debug/clean/lint/lint-strict/test` vérifiés sur un clone propre
- [ ] `.gitignore` / README à jour, commit propre
- [ ] **Deadline finale : projet fonctionnel et lintable, prêt pour la peer review, ~19h**
