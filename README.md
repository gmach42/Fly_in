*This project has been created as part of the 42 curriculum by gmach.*

# Fly-in

## Description

Fly-in routes a fleet of drones from a start hub to an end hub through a
network of zones, in as few simulation turns as possible.

The network is read from a map file: zones with coordinates, a type
(`normal`, `priority`, `restricted`, `blocked`) and a capacity
(`max_drones`), linked by bidirectional connections that have their own
capacity (`max_link_capacity`). All drones move simultaneously, turn by turn,
and the program must never put more drones in a zone or on a connection than
it allows. Entering a restricted zone takes 2 turns, and blocked zones can
never be entered.

The program:

- parses and validates the map file, and reports clear errors;
- computes a schedule for every drone;
- prints the moves of each turn in the terminal, in the format required by
  the subject;
- animates the drones on a drawing of the network with pygame.

It reaches the optimal number of turns given by the subject on every map
provided, including the optional challenger map:

| Map | Drones | Turns | Optimum |
|---|---|---|---|
| easy/01_linear_path | 2 | 4 | 4 |
| easy/02_simple_fork | 4 | 4 | 4 |
| easy/03_basic_capacity | 4 | 4 | 4 |
| medium/01_dead_end_trap | 5 | 8 | 8 |
| medium/02_circular_loop | 6 | 10 | 10 |
| medium/03_priority_puzzle | 5 | 6 | 6 |
| hard/01_maze_nightmare | 8 | 13 | 13 |
| hard/02_capacity_hell | 12 | 16 | 16 |
| hard/03_ultimate_challenge | 15 | 26 | 26 |
| challenger/01_the_impossible_dream | 25 | 43 | 43 |

## Instructions

Requirements: Python 3.13 or later and [uv](https://docs.astral.sh/uv/).

```sh
make install      # install the dependencies (uv sync)
make run          # launch the program (python -m src)
make debug        # launch the program under pdb
make lint         # flake8 + mypy with the flags required by the subject
make lint-strict  # flake8 + mypy --strict
make clean        # remove caches (__pycache__, .mypy_cache, ...)
```

Run the commands from the root of the repository.

`make run` opens a menu:

1. Choose a difficulty (Easy, Medium, Hard, Challenger).
2. Choose a map. The maps listed are the `.txt` files of
   `maps/<difficulty>/`, so add your own map files there to try them.
3. The simulation is computed and its turns are printed in the terminal,
   then the drones are animated in the window.
4. Press `ESC` or click "Return to main menu" to go back to the menu.

If a map is invalid or has no path from start to end, the error is printed
in the terminal and the program goes back to the menu instead of crashing.

## Example

Input (`maps/easy/02_simple_fork.txt`):

```
nb_drones: 4

start_hub: start 0 0 [color=green]
hub: junction 1 0 [color=yellow max_drones=2]
hub: path_a 2 1 [color=blue]
hub: path_b 2 -1 [color=blue]
end_hub: goal 3 0 [color=red max_drones=3]

connection: start-junction [max_link_capacity=2]
connection: junction-path_a
connection: junction-path_b
connection: path_a-goal
connection: path_b-goal
```

Output, one line per turn:

```
D1-junction D2-junction
D1-path_a D2-path_b D3-junction D4-junction
D1-goal D2-goal D3-path_a D4-path_b
D3-goal D4-goal
```

The drones split over the two branches: the junction and the start-junction
connection accept 2 drones at a time, while `path_a` and `path_b` accept
only one each.

A drone flying towards a restricted zone is written with the connection it
is on, as written in the map (`D<ID>-<connection>`). With a restricted zone
of capacity 2 between `a` and `goal`:

```
D1-a-restrictedZone
D1-restrictedZone D2-a-restrictedZone
D1-goal D2-restrictedZone
D2-goal
```

Errors, for example an unknown zone type or a map with no path:

```
Error: Line 3: 1 validation error for Zone
Error: No path from 'a' to 'g'
```

## Algorithm and implementation

The code is split into:

| File | Role |
|---|---|
| `src/pydantic_models.py` | `Zone`, `Connection`, `Graph`, `Path` as pydantic models, with the validation rules |
| `src/parser.py` | Reads a map file into a `Graph`, errors reported with their line number |
| `src/pathfinding.py` | A\* and k shortest paths |
| `src/simulation.py` | Schedules the drones and produces the output lines |
| `src/render.py` | pygame menu and animation |
| `src/__main__.py` | Entry point |

### 1. Candidate paths: A\* and k shortest paths

`PathFinder.a_star` finds the cheapest path from the start hub to the end
hub. The cost of a move is the cost of the zone entered: 1 for normal and
priority zones, 2 for restricted zones. Blocked zones are never entered. The
heuristic is the Euclidean distance to the end hub, scaled down so that it
never overestimates the real cost: A\* then always returns an optimal path,
like Dijkstra, while exploring fewer zones. The open set is a binary heap
(`heapq`).

`k_shortest_paths` returns up to `k` distinct paths, cheapest first (k = 10).
It is a simplified version of Yen's algorithm:

1. Run A\* to get the best path.
2. For each connection of that path, run A\* again with this connection
   excluded (on top of the ones already excluded), and keep the result as a
   candidate.
3. Take the cheapest candidate not seen yet, and repeat from step 2 with it.

Any other route has to avoid at least one connection of the current path,
so no path is missed, and the paths come out in increasing cost.

The paths are computed once, before the simulation, and then reused for
every drone.

### 2. Scheduling: prioritized planning with a reservation table

The drones are planned one after the other. For each drone, and for each
candidate path, the program searches the earliest way to follow the path.
At each turn, the drone either waits where it is, or moves to the next zone
of the path. The search explores `(turn, position in the path)` states by
increasing turn, and the first state that reaches the end hub is the
earliest delivery. The drone keeps the path that delivers it first.

Its schedule is then written into a reservation table, which the next
drones have to respect:

- zone slots `(zone, turn)`: at most `max_drones` drones in a zone at the
  end of a turn (the start and end hubs are unlimited);
- link slots `(connection, turn)`: at most `max_link_capacity` drones
  using a connection during a turn.

This table implements the movement rules of the subject:

- only the occupancy at the end of a turn is counted, so a zone freed during
  a turn can be entered in the same turn (a column of drones advances one
  step per turn);
- a move into a restricted zone takes 2 turns. The drone uses the connection
  on the first turn only, since the subject frees a restricted connection on
  the arrival turn, and a slot must be free in the zone on the second turn.
  A drone therefore never starts a flight it cannot finish, and never waits
  on a connection.

Why this approach:

- **No conflict and no deadlock by construction.** Every schedule respects
  all the reservations made before it. A drone can always wait in the start
  hub, which is unlimited, until the way is clear, so a schedule always
  exists as soon as a path exists.
- **Distribution across paths and strategic waiting come for free.** When
  the cheapest path is saturated, a drone either takes another path or
  waits, whichever delivers it earlier.
- **It anticipates.** A turn-by-turn simulation cannot start a drone towards
  a restricted zone that is still occupied, even when that zone will be free
  when the drone arrives. The reservation table knows it, which is what lets
  drones enter a restricted zone at every turn on `circular_loop` (10 turns
  instead of 15).

### Complexity and memory

- **Pathfinding:** A\* is O(E log V) with the binary heap. `k_shortest_paths`
  runs A\* about k × (path length) times, once, before the simulation.
- **Scheduling:** for each of the D drones and each of the k paths, the
  search visits at most L × H states, where L is the path length and H the
  number of turns explored (the last reserved turn plus 2 × L). The total is
  about O(D × k × L × H).
- **Memory:** the reservation table holds one entry per zone or link used
  per turn, so O(D × T) for T turns, plus one plan of T steps per drone.

## Visual representation

The simulation is shown in a pygame window:

- **The network:** each zone is a circle drawn in the `color` given in the
  map file (gray when none is given), with its name below it. The
  connections are drawn as lines.
- **The drones** are drawn as small potatoes (`potato.png`). They glide
  from their position at one turn to their position at the next, at one
  turn per second.
- **Restricted moves:** a drone flying towards a restricted zone stops in
  the middle of the connection for one turn, which shows the 2-turn cost.
- **Several drones in one zone** are drawn slightly shifted from each
  other, so that they stay visible.
- **The terminal** shows the same turns as text, in the subject's format.

Watching the animation makes the schedule easy to follow:

- where drones queue in front of a low-capacity zone;
- how they split over several paths;
- when a drone waits instead of moving.

## Resources

- [pygame-ce documentation](https://pyga.me/docs/) and
  [pygame documentation](https://www.pygame.org/docs/)
- [Handling a title screen and buttons in pygame](https://programmingpixels.com/handling-a-title-screen-game-flow-and-buttons-in-pygame.html),
  used as a basis for the menu
- [pydantic documentation](https://docs.pydantic.dev/latest/): models and
  validators
- [Introduction to A\*](https://www.redblobgames.com/pathfinding/a-star/introduction.html)
  (Red Blob Games)
- [Yen's algorithm](https://en.wikipedia.org/wiki/Yen%27s_algorithm) for
  the k shortest paths
- D. Silver, [*Cooperative Pathfinding*](https://ojs.aaai.org/index.php/AIIDE/article/view/18726)
  (AIIDE 2005): prioritized planning with a space-time reservation table
- Python documentation for [`heapq`](https://docs.python.org/3/library/heapq.html)

### Use of AI

An AI assistant (Claude, from Anthropic, through Claude Code) was used
during the project:

- **Pathfinding:** rewriting `k_shortest_paths` so that it finds every
  alternative route, not only those that avoid the first connection.
- **Simulation:** designing and writing `simulation.py`, the scheduling
  with a reservation table, first as a turn-by-turn engine, then as the
  current version to follow the restricted-zone rules of the subject and
  reach the optimum.
- **Rendering:** connecting the simulation to the pygame window and
  writing the drone animation.
- **Code quality:** adding type hints so that flake8 and mypy pass, and
  turning `src/` into a package so that no `sys.path` workaround is needed.
- **Testing:** writing throwaway scripts that replay every turn and check
  the capacity rules on all the maps. These scripts are not part of the
  repository.
- **Documentation:** writing this README.

All the code produced with the AI was reviewed, tested on every map and
reworked by the author, who can explain every part of it.
