"""SUPERPAC - an adaptive, opponent-modelling AI for a multiplayer grid game.

Quick start
-----------

Play it in the development simulator::

    from superpac import SuperPac, standard_scenarios, run_game
    from superpac.bots.simple import GreedyFoodBot

    run_game([SuperPac, lambda: GreedyFoodBot(1)],
             standard_scenarios(1, 2)[0])

Find out what the real tournament API looks like (run once, inside the real
engine, with whatever object it hands your player)::

    from superpac import inspect_api
    print(inspect_api(state))

Everything the outside world touches lives in two places: :class:`RuleSet` for
the rules and :class:`StateExtractor` for the host object's shape.  The AI
itself never sees either - it reads :class:`GameState`.  See ``docs/GAME_API.md``.
"""

from .ai.evaluator import DEFAULT_WEIGHTS, Weights
from .ai.strategy import Mode
from .ai.superpac import SuperPac
from .game.adapter import Schema, StateExtractor, describe_host_state
from .game.map_model import MapGraph
from .game.rules import (ACTION_NAMES, ALL_ACTIONS, DEFAULT_RULES, EAST, NORTH,
                         RULE_VARIANTS, SOUTH, STAY, WEST, RuleSet)
from .game.state import GameState
from .opponents.model import OpponentModel, OpponentRegistry
from .simulation.engine import Engine
from .simulation.scenario import MapSpec, Scenario, standard_scenarios
from .simulation.tournament import head_to_head, run_game, run_tournament

#: One-shot diagnostic: hand it a real host state object and it reports what
#: the sniffer found.  See ``docs/GAME_API.md``.
inspect_api = describe_host_state

__version__ = "1.0"

__all__ = [
    # agent
    "SuperPac", "Weights", "DEFAULT_WEIGHTS", "Mode",
    # world
    "GameState", "MapGraph", "RuleSet", "DEFAULT_RULES", "RULE_VARIANTS",
    "NORTH", "SOUTH", "EAST", "WEST", "STAY", "ACTION_NAMES", "ALL_ACTIONS",
    # host integration
    "StateExtractor", "Schema", "inspect_api", "describe_host_state",
    # opponent modelling
    "OpponentModel", "OpponentRegistry",
    # simulation
    "Engine", "Scenario", "MapSpec", "standard_scenarios",
    "run_game", "run_tournament", "head_to_head",
    "__version__",
]
