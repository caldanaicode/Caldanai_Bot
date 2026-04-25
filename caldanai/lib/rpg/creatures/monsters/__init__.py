from os import sep
from random import choice, random, sample
from typing import Dict, List, Optional, Type, Union

from caldanai import PluginManager
from caldanai.lib.rpg import GameClock, parse
from caldanai.lib.rpg.combat.resolution import compute_body_hp_damage
from caldanai.lib.rpg.creatures import Creature, round_robin_assignment
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

    # Q.6 creature-wide bleed multiplier applied on top of per-part
    # ``BodyPart.bleed_rate`` in the body-HP damage formula. No-op at
    # 1.0; content populates per-monster after Q.6 lands (skeleton
    # 0.3 for no-fluid, vampire 1.2 for thematic, golem 0.5 for
    # stone body, etc.).
    BLEED_MOD: float = 1.0

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

    def on_pre_retaliation(self, damage_by_player: list) -> str:
        """Called after players attack but BEFORE the monster retaliates.
        Override to surface narration that contextualizes the monster's
        upcoming attack — e.g. a cyclops bellowing in agony as it
        transitions to a blind rampage, a doppelganger imitating the
        hardest hitter before swinging back, a werewolf's desperation
        flaring near dawn. The narration lands above the retaliation
        attack table because it explains the attack that follows.

        :param damage_by_player: List of (Player, int) tuples with
            damage dealt this round.
        :return: An optional message string to display, or empty string.
        """
        return ""

    def on_combat_round(self, damage_by_player: list) -> str:
        """Called AFTER the monster retaliates. Override for post-
        retaliation state mutation (and any narration that describes
        consequences of the monster's own attack) — e.g. hydra ticking
        breath cooldowns and regrowing severed heads. The returned
        narration lands below the retaliation attack table.

        For narration that *causes* the retaliation (rage, desperation,
        transformation), override :meth:`on_pre_retaliation` instead so
        it lands above the attack table.

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

    def attack_random(self, combatants: list, count=1) -> Optional[str]:
        """Attack ``count`` randomly chosen combatants and return the
        rendered attack markdown plus any resulting injury / death
        messages.

        Thin driver over the Phase 2-3 base pipeline stages — mirrors
        :meth:`Hydra.attack_random`'s shape. ``pick_actions`` walks
        body-part ``DEFAULT_ACTIONS`` pools, ``pick_targets`` pairs each
        action with a victim (round-robin for ``count > 1``, single-
        target otherwise), ``resolve`` routes per-part damage, and the
        narration stages compose the output.

        ``narrate_attempt`` output is deliberately suppressed here to
        preserve today's "no pre-attack narrative for plain monsters"
        shape — hydra composes its own per-head paragraph inside its
        own override. Phase 6b is a structural port; adding attempt
        narration for every monster is a content-pass decision.

        Body HP is still applied per-victim with a
        ``max(num_hits, total - defense)`` floor so defense can't
        trivialize every hit in a multi-source attack. ``resolve``
        stopped applying body HP in Phase 6a, so this method owns the
        whole-body write (and the death-transition message it returns).
        """
        if not combatants or not (0 < count <= len(combatants)):
            return None

        victims = sample(combatants, count)

        actions = self.pick_actions()
        if not actions:
            return None

        if len(victims) > 1:
            assignments = round_robin_assignment(actions, victims)
        else:
            assignments = self.pick_targets(actions, victims)
        if not assignments:
            return None

        results = self.resolve(assignments)
        table = self.render_table(results)
        injury_lines = self.narrate_results(results)

        msg = table
        if injury_lines:
            msg += "\n".join(injury_lines) + "\n"

        for victim in victims:
            resolution = (results.per_victim or {}).get(victim)
            if resolution is None or resolution.num_hits == 0:
                continue

            death_msg = resolution.death_msg

            if not victim.is_dead():
                final = compute_body_hp_damage(resolution, victim)
                d_msg = victim.apply_damage(final)
                if d_msg and not death_msg:
                    death_msg = d_msg

            if death_msg:
                msg += parse(death_msg, victim)

        return msg

    # Extra names this plugin should resolve from, beyond its filename
    # stem. Populated per-plugin where the in-fiction display name
    # diverges from the stem (``MathTeacher.ALIASES = ["flying math
    # teacher"]``) or where a plugin has multiple valid display names
    # at runtime (hydra variants). Case-insensitive; stem is always
    # registered automatically.
    ALIASES: "List[str]" = []

    @classmethod
    def load_plugins(cls) -> None:
        """Load all monster plugin files under :attr:`BASEPATH`.

        After :class:`PluginManager` finishes filesystem discovery, the
        name-keyed ``_PLUGIN_REGISTRY`` is rebuilt. Keys come from:

        - The plugin's module filename stem (``goblin``, ``math_teacher``).
          Always registered — this is the canonical API-friendly name.
        - Each ``ALIASES`` entry the plugin declares — the in-fiction
          display names a player would naturally type. ``MathTeacher``
          registers ``"flying math teacher"``; ``Hydra`` registers its
          variant display names (``"swamp hydra"`` / ``"hexed hydra"`` /
          ``"elemental hydra"``).

        Registry keys are lowercased on insertion. Conflicts between
        two plugins' aliases are resolved first-write-wins (deterministic
        since plugin load order is alphabetical by filename); a future
        collision would need explicit scoping.
        """
        PluginManager.load(MonsterPlugin, MonsterPlugin.BASEPATH)

        registry: Dict[str, Type["MonsterPlugin"]] = {}
        for plugin_cls in PluginManager.LOADED_PLUGINS.get(MonsterPlugin, []):
            stem = plugin_cls.__module__.rsplit(".", 1)[-1].lower()
            if stem:
                registry.setdefault(stem, plugin_cls)
            for alias in getattr(plugin_cls, "ALIASES", []) or []:
                key = alias.lower().strip()
                if key:
                    registry.setdefault(key, plugin_cls)
        MonsterPlugin._PLUGIN_REGISTRY = registry

    @classmethod
    def get_plugin_class(
        cls, name: str,
    ) -> Optional[Type["MonsterPlugin"]]:
        """Look up a loaded monster plugin class by name.

        Matches case-insensitively against the filename stem AND any
        class-declared ``ALIASES`` of each loaded plugin. ``"goblin"``,
        ``"math_teacher"``, ``"flying math teacher"``, ``"swamp hydra"``
        all resolve via this single lookup.

        Returns ``None`` if the name is unknown (or if
        :meth:`load_plugins` has never been called). For fuzzy
        resolution against partial queries, see
        :meth:`find_plugin_classes`.
        """
        if not name:
            return None
        return MonsterPlugin._PLUGIN_REGISTRY.get(name.lower().strip())

    @classmethod
    def find_plugin_classes(
        cls, query: str,
    ) -> "List[Type[MonsterPlugin]]":
        """Fuzzy lookup — returns every plugin class whose stem or
        alias matches ``query`` under the same two-pass rules
        :meth:`Creature.find_parts` uses: exact, then per-whitespace-
        token prefix, then per-token substring fallback.

        Dedupes on the plugin class itself — ``"hydra"`` matches the
        stem AND three of its variant aliases, but returns
        :class:`Hydra` once.

        Callers (typically ``Game.do_spawn``) treat the result as:

        - empty → "unknown monster"
        - one match → spawn it
        - many matches → ambiguous; prompt the user with the list

        Whitespace is the token separator (``"flying math"`` has two
        query tokens that must each match SOME name token, no
        positional requirement — multi-word display names are
        phrases, not structured paths). Dots are treated as
        whitespace for friendliness since some operators may reach
        for ``math.teacher`` out of body-part-targeting habit.
        """
        q = query.lower().strip() if query else ""
        if not q:
            return []

        registry = MonsterPlugin._PLUGIN_REGISTRY

        # Exact — short-circuit, single-class result.
        if q in registry:
            return [registry[q]]

        q_tokens = q.replace(".", " ").split()
        if not q_tokens or any(not t for t in q_tokens):
            return []

        def tokens(name: str) -> List[str]:
            return name.replace("_", " ").replace(".", " ").split()

        def unordered_prefix_match(name: str) -> bool:
            name_tokens = tokens(name)
            # Every query token must be a prefix of SOME name token.
            # Ordering doesn't matter — ``"teacher flying"`` should
            # resolve the same as ``"flying teacher"``.
            return all(
                any(nt.startswith(qt) for nt in name_tokens)
                for qt in q_tokens
            )

        def unordered_substring_match(name: str) -> bool:
            name_tokens = tokens(name)
            return all(
                any(qt in nt for nt in name_tokens)
                for qt in q_tokens
            )

        def collect(matcher) -> "List[Type[MonsterPlugin]]":
            seen: set = set()
            out: "List[Type[MonsterPlugin]]" = []
            for key, plugin_cls in registry.items():
                if matcher(key) and plugin_cls not in seen:
                    seen.add(plugin_cls)
                    out.append(plugin_cls)
            return out

        prefix_hits = collect(unordered_prefix_match)
        if prefix_hits:
            return prefix_hits
        return collect(unordered_substring_match)
