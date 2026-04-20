from os import sep
from random import choice, random, sample
from typing import Dict, List, Optional, Type, Union

from caldanai import PluginManager
from caldanai.lib.rpg import GameClock, parse
from caldanai.lib.rpg.combat.attack_source import AttackSource
from caldanai.lib.rpg.combat.resolution import apply_sequence_to_target
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import (AggressionLevels, DamageTypes,
                                            TimePartitions, TimesOfDay,
                                            WeatherPatterns)
from caldanai.lib.rpg.inventory import Inventory, Item
from caldanai.logger import get_logger

_log = get_logger(__name__)



class MonsterPlugin(Creature):
    """Base class for Monster-type plugins. This class should not be
    instantiated directly."""

    BASEPATH: str = sep.join([
        'caldanai',
        'lib',
        'rpg',
        'creatures',
        'monsters'
    ])

    # Name-keyed registry populated by :meth:`load_plugins`. Mirrors
    # ``BodyPartPlugin._PLUGIN_REGISTRY``: keys are the monster plugin's
    # filename stem (e.g. ``"goblin"``, ``"math_teacher"``) so admin
    # ``$spawn monster <name>`` can look a class up without re-globbing
    # the filesystem on every invocation. Filename is used (not class
    # ``__name__``) so ``MathTeacher`` stays reachable as
    # ``math_teacher`` — the same token the old filesystem scan matched.
    _PLUGIN_REGISTRY: Dict[str, Type["MonsterPlugin"]] = {}

    # Layer-2 action repertoire — nested by part type then action
    # name. The outer key is the part plugin's ``name`` (``"head"``,
    # ``"arm"``, etc.); inner keys are action names. Entries both
    # MODIFY matching part-default actions (field-level overlay) and
    # ADD entirely new actions that the part didn't declare (e.g.
    # a minotaur's ``head.gore``). Each entry is the same shape as a
    # ``DEFAULT_ACTIONS`` entry — dice / dmg_type / reach / label /
    # weight / cost / narrative / optional callable fields. Empty
    # until Phase 6+ ports per-monster flavor; Phase 3 ships the
    # mechanism only.
    ACTION_REPERTOIRE: Dict[str, Dict[str, Dict]] = {}

    def __init__(
            self,
            name: Optional[str],
            atk: Optional[str],
            defense: Optional[Union[str, int]],
            dodge: Optional[Union[str, int]],
            health_max: Optional[Union[str, int]],
            health: Optional[int] = None,
            gender: Optional[str] = None,
            pronouns: Optional[str] = None
    ):
        super().__init__(
            name, atk, defense, dodge, health_max, health, gender, pronouns)

        self.aggression = AggressionLevels.PASSIVE
        self.time_partition = TimePartitions.CATHEMERAL
        # Weather mask: which weather conditions can this monster
        # spawn into? Default = any. Override per-monster with flag
        # masks like ``WeatherPatterns.FOG`` (fog wraiths, only
        # spawns in fog), ``WeatherPatterns.PRECIPITATION |
        # WeatherPatterns.WIND`` (storm elementals), or
        # ``WeatherPatterns.CLEAR`` (sun-lovers). Matched against
        # ``game.weather.active_patterns`` in ``get_random_monster``.
        self.weather_partition = WeatherPatterns.ALL
        self.dies_from_time = False
        self.time_death = ""
        self.flees_from_time = False
        self.time_flee = ""
        self.arrival = ""
        self.flavor = ""
        self.escape = ""
        self.death = ""
        self.loot: Dict[str, float] = {}
        # Items potentially left behind on a time-based flee (e.g. a
        # werewolf bolting at dawn drops a shred of the human form's
        # clothing). Same ``name -> drop_chance`` shape as ``loot``.
        # NOTE: ``get_flee_loot`` is currently a dead hook — no engine
        # caller yet. Wiring into ``Game.check_time`` (and/or
        # equivalent escape paths) is a follow-up when we generalize
        # "monster leaves evidence behind" as a first-class concept.
        self.flee_loot: Dict[str, float] = {}

    def on_combat_round(self, damage_by_player: list) -> str:
        """Called after players attack but before the monster retaliates.
        Override to react to per-player damage dealt this round.

        :param damage_by_player: List of (Player, int) tuples with damage dealt this round.
        :return: An optional message string to display, or empty string.
        """
        return ""

    def on_spawn(self, game) -> str:
        """Called after the monster is placed into the game. Override to perform
        setup that requires access to the game state (players, channel, etc.).

        :param game: The Game instance this monster was spawned into.
        :return: An optional message string to display, or empty string.
        """
        return ""

    def on_target_part_destroyed(
        self, victim: Creature, part: BodyPart,
    ) -> str:
        """Hook called by ``attack_random`` the first time one of this
        monster's attacks destroys a target's body part. Override to
        emit monster-specific narration (e.g. werewolf throat-bite on a
        destroyed head). Default: no-op.

        Fires in addition to ``part.on_destroyed`` — the part-side hook
        describes the injury from the victim's perspective, this one
        describes it from the attacker's. Both feed the same injury
        feedback block in ``attack_random``.
        """
        return ""

    def apply_damage(
        self,
        amount: int,
        dmg_type: Optional[DamageTypes] = None,
        target_part: Optional[BodyPart] = None,
    ) -> Optional[str]:
        was_alive = self.health > 0
        super().apply_damage(
            amount,
            dmg_type=dmg_type,
            target_part=target_part,
        )
        if was_alive and self.is_dead():
            return self.death

        return ""

    @staticmethod
    def get_random_monster(
        clock: GameClock,
        weather: Optional[WeatherPatterns] = None,
    ) -> Optional['MonsterPlugin']:
        """Retrieves a random monster plugin appropriate for the
        current time-of-day and (if supplied) weather.

        Time filter: bitwise overlap between the current
        ``TimesOfDay`` and the monster's ``time_partition``.
        Weather filter: bitwise overlap between the current
        ``WeatherPatterns`` and the monster's ``weather_partition``.
        Weather defaults to ``ALL`` both for the argument (caller may
        not have weather state) and for per-monster partitions, so
        the filter is permissive unless explicitly narrowed.
        """
        time = TimesOfDay[clock.get_time_of_day().upper()].value
        active_weather = weather if weather is not None else WeatherPatterns.ALL

        candidates = []
        for cls in PluginManager.LOADED_PLUGINS[MonsterPlugin]:
            instance = cls()
            if not bool(time & instance.time_partition):
                continue
            if not bool(active_weather & instance.weather_partition):
                continue
            candidates.append(cls)

        if not candidates:
            return None

        return choice(candidates)()

    def get_flee_loot(self) -> list:
        """Returns items potentially left behind when the monster flees
        due to time-of-day (``flees_from_time``). Mirrors ``get_loot``
        but rolls against ``self.flee_loot`` instead.

        Not yet wired into the engine — see ``flee_loot`` attribute
        comment. Available as a hook point for monster implementations
        that want to declare "what I leave in my wake".
        """
        items: List[Item] = []
        for name, freq in self.flee_loot.items():
            if name not in Inventory.ITEMS.keys():
                Inventory.discover_items()

            if name in Inventory.ITEMS.keys():
                if random() <= freq:
                    item = Inventory.ITEMS[name].from_plugin(name, {})
                    if item:
                        items.append(item)
            else:
                _log.warning(f"No such item '{name}' found in the Inventory.ITEMS list.")

        return items

    # Returns a list of loot items
    def get_loot(self) -> list:
        items: List[Item] = []
        for name, freq in self.loot.items():
            if name not in Inventory.ITEMS.keys():
                Inventory.discover_items()

            if name in Inventory.ITEMS.keys():
                if random() <= freq:
                    item = Inventory.ITEMS[name].from_plugin(name, {})
                    if item:
                        items.append(item)
            else:
                _log.warning(f"No such item '{name}' found in the Inventory.ITEMS list.")

        return items

    def attack_random(self, combatants: list, count=1) -> str:
        """Attack ``count`` randomly chosen combatants and return the
        rendered attack markdown plus any resulting injury / death
        messages.

        Mirrors the player-attacks-monster path in ``Game.do_combat``:
        per-result damage routes to the targeted body part for injury
        tracking (no body-HP touch), injury-level transitions coalesce
        across the sequence into one message per part, and the
        post-defense total hits body HP once via ``victim.apply_damage``
        so the victim's own death-transition detection still fires.

        Defense is subtracted from the per-victim total (variant B),
        with a ``max(num_hits, total - defense)`` floor so defense
        can't trivialize every hit in a multi-source attack.
        """
        if not combatants or not (0 < count <= len(combatants)):
            return None

        victims = sample(combatants, count)
        msg = ""
        for victim in victims:
            sequence = self.do_attack(victim)
            msg += sequence.to_markdown()

            # Per-result part routing + coalesced injury feedback +
            # part-side hooks + attacker-side
            # ``on_target_part_destroyed`` all happen inside the helper.
            # Passing ``attacker=self`` is what distinguishes the
            # monster -> player path from the (``attacker=None``) player
            # -> monster path in ``Game.do_combat``.
            resolution = apply_sequence_to_target(
                sequence, victim, attacker=self,
            )
            if resolution.num_hits == 0:
                continue

            death_msg = resolution.death_msg

            # Body HP: apply post-defense total once via the whole-body
            # path so the victim's death-transition messaging fires.
            if not victim.is_dead():
                defense = victim.get_defense()
                final = max(
                    resolution.num_hits,
                    resolution.body_damage_total - defense,
                )
                d_msg = victim.apply_damage(final)
                if d_msg and not death_msg:
                    death_msg = d_msg

            # Injury feedback first, then the death beat — death is
            # the narrative crescendo for this victim and reads
            # correctly as the last line. ``do_combat`` and
            # ``Hydra.attack_random`` already order their per-victim
            # sections this way.
            if resolution.injury_feedback_lines:
                msg += "\n".join(resolution.injury_feedback_lines) + "\n"
            if death_msg:
                msg += parse(death_msg, victim)

        return msg

    @classmethod
    def load_plugins(cls) -> None:
        """Load all monster plugin files under :attr:`BASEPATH`.

        After :class:`PluginManager` finishes filesystem discovery, the
        filename-keyed ``_PLUGIN_REGISTRY`` is rebuilt so
        :meth:`get_plugin_class` can resolve a name without touching
        disk. The registry key is the plugin's module filename stem
        (``cls.__module__.rsplit('.', 1)[-1]``) — the same token the
        old ``Game.get_monster`` filesystem scan matched.
        """
        PluginManager.load(MonsterPlugin, MonsterPlugin.BASEPATH)

        registry: Dict[str, Type["MonsterPlugin"]] = {}
        for plugin_cls in PluginManager.LOADED_PLUGINS.get(MonsterPlugin, []):
            key = plugin_cls.__module__.rsplit(".", 1)[-1].lower()
            if key:
                registry[key] = plugin_cls
        MonsterPlugin._PLUGIN_REGISTRY = registry

    @classmethod
    def get_plugin_class(
        cls, name: str,
    ) -> Optional[Type["MonsterPlugin"]]:
        """Look up a loaded monster plugin class by name.

        Matches case-insensitively against the filename stem of each
        loaded plugin (e.g. ``"goblin"``, ``"math_teacher"``). Mirrors
        the case-handling the pre-refactor filesystem scan provided:
        ``"Goblin"``, ``"GOBLIN"`` and ``"goblin"`` all resolve to
        :class:`Goblin`.

        Returns ``None`` if the name is unknown (or if
        :meth:`load_plugins` has never been called). Callers —
        notably :meth:`Game.get_monster` — are responsible for the
        user-facing error message on miss.
        """
        if not name:
            return None
        return MonsterPlugin._PLUGIN_REGISTRY.get(name.lower())
