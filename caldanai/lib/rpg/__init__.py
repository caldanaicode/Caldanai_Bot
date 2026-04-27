import inspect
import random
from collections import Counter

from discord import Guild, TextChannel
from typing import Any, Callable, Dict, List, Tuple, Union, Optional, TYPE_CHECKING
from random import choice, randint

from caldanai.lib.rpg.helpers.enums import AggressionLevels, TimesOfDay, Roles
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.areas import Area
from caldanai.lib.rpg.time import GameClock
from caldanai.lib.rpg.helpers import get_random_direction

# Discord-renderable indent: U+2800 BRAILLE PATTERN BLANK, four wide.
# Imported by ``caldanai.lib.rpg.creatures`` for its own total-damage
# row, so it MUST be defined before the imports below that trigger
# circular loading of the creatures package \u2014 otherwise that package
# sees a partially-initialized ``caldanai.lib.rpg`` without
# ``_INDENT`` yet bound and the import fails.
_INDENT = "\u2800" * 4

from caldanai.lib.rpg.combat.resolution import (
    apply_sequence_to_target,
    compute_body_hp_damage as _compute_body_hp_damage,
)
from caldanai.lib.rpg.combat_state import CombatState
from caldanai.lib.rpg.ambience.celestial import CelestialDaemon
from caldanai.lib.rpg.ambience.weather import WeatherDaemon
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.player_manager import PlayerManager
from caldanai.lib.rpg.inventory.item import Item
from caldanai.lib.rpg.inventory.equipment.weapons import Weapon
from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.db import DB

if TYPE_CHECKING:
    from caldanai.lib.bot import Bot


_log = get_logger(__name__)


# Number-words for salvage-narration coalescing (1-10 spell out;
# 11+ falls through to digit form). Both call sites — the inline
# salvage in ``_run_player_block`` and the corpse-scavenge sweep in
# ``on_monster_death`` — reuse :func:`_render_salvage_lines` so
# count/plural/verb logic stays in one place.
_SALVAGE_COUNT_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}


def _pluralize_salvage_name(name: str) -> str:
    """Append ``"s"`` to the last whitespace-separated word of an
    item's ``name``. Covers every salvage item we ship today
    (``leather`` → ``leathers``, ``patchwork bracer`` →
    ``patchwork bracers``, ``rough rerebrace`` → ``rough rerebraces``,
    ``iron scrap`` → ``iron scraps``). No inflect dependency, no
    irregular-plural table — names that need real plurals (e.g.
    Stackables with their own ``plural`` attribute) aren't in the
    salvage path today."""
    if not name:
        return name
    words = name.split(" ")
    words[-1] = words[-1] + "s"
    return " ".join(words)


def _render_salvage_lines(
    items: "List[Item]",
    owner_phrase: str,
    part_display_name: str,
) -> "List[str]":
    """Render a list of salvage items into one narration line per
    distinct ``(article, name)`` group. Two ``leather`` drops on the
    same destroyed part collapse to ``"Two leathers slip free ..."``;
    a single drop keeps the today-shape ``"Some leather slips
    free ..."``. Quality differences across same-name items don't
    matter for narration — they surface in the post-combat ``$loot``
    summary."""
    if not items:
        return []
    # Group by (article, name) preserving first-seen order so the
    # narration order tracks the salvage roll order. Track one
    # representative item per bucket so plural-aware ``Stackable``
    # entries can carry their explicit ``plural`` attribute through
    # to render-time without re-deriving it from ``name``.
    groups: "Dict[Tuple[str, str], List[Item]]" = {}
    for it in items:
        key = (it.article, it.name)
        groups.setdefault(key, []).append(it)

    lines: "List[str]" = []
    for (article, name), bucket in groups.items():
        count = len(bucket)
        if count == 1:
            subject = f"{article.capitalize()} {name}"
            verb = "slips free"
        else:
            count_word = _SALVAGE_COUNT_WORDS.get(count, str(count))
            # Prefer an explicit ``Stackable.plural`` over the
            # last-word + ``s`` rule. All bucket members share
            # ``(article, name)`` so any representative carries the
            # right plural; future entries like ``wool`` ("tufts of
            # wool") or ``toad slime`` ("globs of toad slime") then
            # render correctly without touching this helper again.
            sample = bucket[0]
            plural_name = (
                getattr(sample, "plural", None)
                or _pluralize_salvage_name(name)
            )
            subject = f"{count_word.capitalize()} {plural_name}"
            verb = "slip free"
        lines.append(
            f"   {subject} {verb} of {owner_phrase} {part_display_name}."
        )
    return lines


class Game:
    # Class-level routing map: Discord channel_id -> Game instance.
    # Populated when a Game registers its primary channel (in
    # ``__init__``) and extended by ``register_channel`` for any
    # spill-over channels (dungeon threads, etc.). Cleared by
    # ``RpgUtilities.remove_game``. Subsystems that need to find
    # the game that owns an arbitrary channel id call ``for_channel``
    # instead of keeping Game references directly — avoids widening
    # Game's surface area across the codebase.
    _channel_routes: "Dict[int, Game]" = {}

    @classmethod
    def for_channel(cls, channel_id: int) -> "Optional[Game]":
        """Return the ``Game`` whose channel-routing set contains
        ``channel_id``, or ``None`` if the channel isn't registered
        with any game. Does NOT perform thread parent-fallback — the
        caller registers thread channels explicitly when a dungeon or
        side-channel opens."""
        return cls._channel_routes.get(channel_id)

    def register_channel(self, channel_id: int) -> None:
        """Route ``channel_id`` to this game. Called automatically
        for the primary channel in ``__init__``; extensible for
        future dungeon / thread channels that want messages from
        ``for_channel`` lookups to resolve to this game."""
        Game._channel_routes[channel_id] = self

    def unregister_channel(self, channel_id: int) -> None:
        """Stop routing ``channel_id`` to this game. Used when a
        dungeon thread closes. No-op if the channel wasn't
        registered."""
        Game._channel_routes.pop(channel_id, None)

    @property
    def channel_id(self) -> "Optional[int]":
        """Primary channel id — the routing key used by the clock
        registry and ``for_channel`` lookups. Derived from
        ``self.channel.id`` (Discord object), or ``None`` when the
        Game has no channel bound (tests, pre-spawn constructions).
        Kept as a property rather than a stored field so it can't
        drift out of sync with ``self.channel``."""
        return self.channel.id if self.channel else None

    # ------------------------------------------------------------------
    # Combat-state proxies
    # ------------------------------------------------------------------
    # These delegate to ``self.combat`` (a ``CombatState``) so external
    # callers — cogs, tests, monster plugins — can keep reading and
    # writing ``game.monster`` / ``game.combatants`` / ``game.loot`` /
    # etc. exactly as before. Setters support whole-field reassignment
    # (``game.combatants = [...]``, ``game.loot = {}``) which a handful
    # of tests rely on.
    @property
    def monster(self) -> "Optional[MonsterPlugin]":
        return self.combat.monster

    @monster.setter
    def monster(self, value: "Optional[MonsterPlugin]") -> None:
        self.combat.monster = value

    @property
    def monsters(self) -> "List[str]":
        return self.combat.monsters

    @monsters.setter
    def monsters(self, value: "List[str]") -> None:
        self.combat.monsters = value

    @property
    def combatants(self) -> "List[Player]":
        return self.combat.combatants

    @combatants.setter
    def combatants(self, value: "List[Player]") -> None:
        self.combat.combatants = value

    @property
    def combat_targets(self) -> "Dict[int, Optional[List[str]]]":
        return self.combat.combat_targets

    @combat_targets.setter
    def combat_targets(self, value: "Dict[int, Optional[List[str]]]") -> None:
        self.combat.combat_targets = value

    @property
    def looters(self) -> "List[Player]":
        return self.combat.looters

    @looters.setter
    def looters(self, value: "List[Player]") -> None:
        self.combat.looters = value

    @property
    def loot(self) -> "Dict[int, List[Union[Item, Weapon]]]":
        return self.combat.loot

    @loot.setter
    def loot(self, value: "Dict[int, List[Union[Item, Weapon]]]") -> None:
        self.combat.loot = value

    # ------------------------------------------------------------------
    # Player lookup shims
    # ------------------------------------------------------------------
    # Thin façade over ``player_manager.players`` so callers outside
    # ``PlayerManager`` don't reach into the underlying dict shape.
    # Mutation (add_player / remove_player) stays on PlayerManager.
    def get_player_by_user_id(self, user_id: int) -> Optional[Player]:
        """Return the player in this game with the given Discord user
        id, or ``None`` if they're not in this game. Shields callers
        from the underlying ``player_manager.players`` dict shape."""
        return self.player_manager.players.get(user_id)

    def _pick_witness(self) -> Optional[Player]:
        """Pick a random player to serve as the ``@2`` slot in any
        monster flavor template (arrival, on_spawn, escape / flee).
        Prefers recently-active players (same threshold as
        :meth:`PlayerManager.update_inactive_roles` — within the
        last day) so the flavor mentions someone who's likely still
        around. Falls back to any known player when nobody's been
        active, and returns ``None`` when the channel has no
        players at all (empty guild / fresh install)."""
        players = list(self.player_manager.players.values())
        if not players:
            return None
        from datetime import datetime, timedelta
        now = datetime.now()
        active = [
            p for p in players
            if getattr(p, "last_active", None)
            and (now - p.last_active) < timedelta(days=1)
        ]
        pool = active or players
        return choice(pool)

    def _build_witness_args(self, monster) -> tuple:
        """Return ``(monster, witness)`` or ``(monster,)`` for use
        as ``*args`` to :func:`parse` on flavor templates that may
        reference ``@2``. The original arrival fix landed inline at
        the spawn site, but escape / flee templates carry the same
        gap (e.g. pixie's "blows a kiss at @2") — this builder
        generalizes the witness pickup so any future ``@2``-bearing
        flavor render can call one place. ``None``-witness collapses
        to a 1-tuple so ``@2``-free templates still render."""
        witness = self._pick_witness()
        return (monster,) if witness is None else (monster, witness)

    def ambience_enabled(self, subsystem: str) -> bool:
        """Return the effective on/off state of an ambience subsystem.

        The master ``enable_ambience`` flag ANDs with each per-
        subsystem flag: a subsystem is "on" only when the master is
        on AND its own flag is on. Subsystem names come from
        :attr:`AMBIENCE_SUBSYSTEMS`. An unknown name treats the
        per-subsystem flag as True (subsystems absent from the
        registry fall back to master-only gating), so adding a new
        subsystem in code without first adding it to the registry
        doesn't silently disable it.
        """
        if not self.enable_ambience:
            return False
        return bool(getattr(self, f"enable_ambience_{subsystem}", True))

    def sync_ambience_daemons(self) -> None:
        """Align every ambience subsystem's scheduling state with the
        current master + per-subsystem flags.

        Called after any flag change (master or sub-toggle) so the
        clock-scheduled routines and per-channel daemons stop or
        start in lockstep with the declared state. Idempotent —
        calling it repeatedly is a no-op when nothing changed, since
        each subsystem's start() / stop() / add_routine() /
        remove_routine() is itself idempotent on its own registry.
        """
        # Local: do_ambience clock routine. add_routine is
        # idempotent (it no-ops if already scheduled); do_ambience
        # self-removes on the next tick when the flag is off, so
        # calling remove_routine directly is defensive but cheap.
        if self.ambience_enabled("local"):
            self.game_clock.add_routine(self.do_ambience, 1)
        else:
            self.game_clock.remove_routine(self.do_ambience)

        # Celestial: sunrise/sunset daemon.
        if self.celestial is not None:
            if self.ambience_enabled("celestial"):
                self.celestial.start()
            else:
                self.celestial.stop()

        # Weather: weather daemon. Requires a season context for
        # the initial roll — import locally to stay consistent with
        # __init__'s pattern and avoid a module-level cycle risk.
        if self.weather is not None:
            if self.ambience_enabled("weather"):
                from caldanai.lib.rpg.helpers.enums import Seasons
                self.weather.start(Seasons(self.game_clock.get_season()))
            else:
                self.weather.stop()

    # Canonical list of ambience subsystems. Each name corresponds to
    # a per-subsystem kill-switch stored as
    # ``enable_ambience_<name>`` on the Game and gated at emit time
    # below. Kept as a class-level tuple so the admin command, the
    # serializer, and the synchronization helper all agree on the set
    # without duplicating it.
    AMBIENCE_SUBSYSTEMS: Tuple[str, ...] = ("local", "celestial", "weather")

    def __init__(
        self,
        bot: "Bot" = None,
        game_id: str = None,
        guild: Guild = None,
        channel: TextChannel = None,
        use_spawn_timer: bool = True,
        spawn_range: Tuple[int, int] = (600, 3600),
        spawn_duration: int = 10,
        loot_duration: int = 5,
        enable_ambience: bool = True,
        enable_ambience_local: bool = True,
        enable_ambience_celestial: bool = True,
        enable_ambience_weather: bool = True,
        game_time: int = 0,
    ):
        """
        Initialize a new Game object.

        :param bot: The bot that owns this game.
        :param game_id: The game's database ID.
        :param guild: The guild (a.k.a. server) that hosts this game.
        :param channel: The channel to which this game sends most responses.
        :param use_spawn_timer: Whether to allow periodic monster spawns.
        :param spawn_timer_range: The minimum and maximum time between spawns, in seconds.
        :param spawn_duration: Number of minutes before first combat triggers. Additional rounds occur at half this time.
        :param loot_duration: Number of minutes before loot expires.
        :param enable_ambience: Master kill-switch for all ambience
            subsystems. When ``False``, no subsystem emits regardless
            of its own flag — the master ANDs with each subsystem.
        :param enable_ambience_local: Sub-toggle for random local
            flavor lines (wildlife, breezes, etc.) emitted by
            :meth:`do_ambience`.
        :param enable_ambience_celestial: Sub-toggle for sunrise /
            sunset (and future celestial-traversal) narration.
        :param enable_ambience_weather: Sub-toggle for weather-
            pattern narration emitted by the ``WeatherDaemon``.
        :param game_time: The game's internal time value.
        """
        self.bot = bot
        self.id = game_id  # Mongo ObjectId — DB document identity only.
        self.guild = guild
        self.channel = channel
        # Primary Discord channel id (``self.channel.id``) is the
        # routing key for the clock registry and ``for_channel``
        # lookups. Accessed via the ``channel_id`` property below so
        # it can't drift out of sync with ``self.channel``.
        self.player_manager: PlayerManager = PlayerManager(channel=channel)
        # Combat-runtime state lives on ``self.combat`` (a
        # ``CombatState``) rather than as individual fields on
        # ``Game``. Property accessors below preserve the legacy
        # ``game.monster`` / ``game.combatants`` / ``game.loot`` etc.
        # surface for cogs, tests, and monster hooks.
        self.combat: CombatState = CombatState()
        # How the most recent combat ended — ``"death"`` if the
        # monster fell, ``"flee"`` if it bolted, ``None`` before any
        # combat. Read by ``$loot`` to branch wording (a corpse
        # exists for "death", a fled monster for "flee"). Persists
        # past ``end_combat``; reset only when a new combat starts.
        self.last_combat_outcome: Optional[str] = None
        self.use_spawn_timer = use_spawn_timer
        self.spawn_duration = spawn_duration * 60
        self.loot_duration = loot_duration * 60
        self.loot_countdown = loot_duration * 60
        self.spawn_timer_range = spawn_range
        self.enable_ambience = enable_ambience
        self.enable_ambience_local = enable_ambience_local
        self.enable_ambience_celestial = enable_ambience_celestial
        self.enable_ambience_weather = enable_ambience_weather
        self.game_clock = GameClock(
            game_time=game_time,
            channel_id=channel.id if channel else None,
        )
        # WeatherDaemon + CelestialDaemon are created here but
        # not started — starting schedules routines on the clock
        # registry, which requires the game to be registered. Both
        # happen below together.
        self.weather = WeatherDaemon(channel.id) if channel else None
        self.celestial = CelestialDaemon(channel.id) if channel else None
        self.room0: Area = None
        self.monster_statics: Counter = Counter()

        if guild:
            self.game_clock.add_routine(self.player_manager.update_inactive_roles, 3600)
            self.prefix = DB.get_server_by_guild_id(guild.id)["prefix"]

        if self.enable_ambience or self.use_spawn_timer:
            _log.info(f"Game clock starting for {game_id}")
            self.game_clock.tick.start()
            # Regen timer is triggered every game hour (15 minutes for default time scale)
            # Regen ticks every 30 game-minutes (7.5 real-min at
            # time_scale=4). Keeps recovery pacing playable in a
            # typical session without making injuries trivial.
            self.game_clock.add_routine(self.player_manager.do_health_regen, 1800 / self.game_clock.time_scale)

        if use_spawn_timer:
            self.game_clock.add_routine(self.set_spawn_timer, 5, True)
        # Random-flavor ambience routine. Gated by the combined
        # "master AND local" check so a game created with
        # ``enable_ambience_local=False`` skips scheduling entirely
        # — same behavior as the old master-only gate, extended with
        # the subsystem dimension.
        if self.ambience_enabled("local"):
            self.game_clock.add_routine(self.do_ambience, 1)

        self.bot = bot

        # Register with the channel routing map so downstream
        # subsystems can find this game (and its clock) without
        # holding a Game reference. Idempotent no-op when
        # ``channel_id`` is None (tests / pre-spawn contexts).
        # ``Bot.games`` is now a read-only property over
        # ``_channel_routes``, so the channel-routing registration
        # below is the one-and-only place the Bot-level map is
        # populated — no separate ``bot.games[...] = self`` write.
        # ``GameClock.for_channel`` resolves through this same
        # registry, so there is no separate clock registration step.
        if self.channel_id is not None:
            self.register_channel(self.channel_id)
            # Start the weather daemon *after* clock registration
            # (it schedules itself via the clock-registry façade).
            # Ambience subsystems are enabled under the same gate as
            # the existing ambience loop — ``enable_ambience=False``
            # is used by tests / headless contexts.
            if self.weather is not None and self.ambience_enabled("weather"):
                from caldanai.lib.rpg.helpers.enums import Seasons
                self.weather.start(Seasons(self.game_clock.get_season()))
            # Sunrise/sunset narration is a separate daemon now
            # (previously inline in do_ambience); gated by the
            # combined master + celestial flags.
            if self.celestial is not None and self.ambience_enabled("celestial"):
                self.celestial.start()

    @staticmethod
    def if_connected(method: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(method):

            async def async_wrapper(self: "Game", *args, **kwargs) -> Any:
                if not self.bot.is_online_discord:
                    _log.error("The bot does not appear to be connected to Discord.")
                    return
                return await method(self, *args, **kwargs)

            return async_wrapper

        else:

            def sync_wrapper(self: "Game", *args, **kwargs) -> Any:
                if not self.bot.is_online_discord:
                    _log.error("The bot does not appear to be connected to Discord.")
                    return
                return method(self, *args, **kwargs)

            return sync_wrapper

    async def check_time(self):
        if (
            not self.monster
            or self.monster.is_dead()
            or (not self.monster.flees_from_time and not self.monster.dies_from_time)
        ):
            self.game_clock.remove_routine(self.check_time)
            return

        monster = self.monster
        tod = self.game_clock.get_time_of_day()
        h, m, _ = self.game_clock.get_time_components()
        next_tod, next_h, next_m = self.game_clock.get_next_time()
        flee = not bool(monster.time_partition & TimesOfDay[tod.upper()].value)
        next_flee = not bool(monster.time_partition & TimesOfDay[next_tod.upper()].value)
        msg = ""

        if flee and monster.dies_from_time:
            msg = monster.time_death
            msg += await self.on_monster_death()

        elif monster.flees_from_time:
            remaining = ((24 if h > next_h else 0) + next_h + next_m / 60) - (h + m / 60)
            if flee or (next_flee and remaining < 1 / 6):
                msg = monster.time_flee
                self.monster_statics[f"{self.monster.name}.fled"] += 1
                # ``cancel_combat`` returns the loot-announce text
                # when mid-combat salvage sits in the pool. Append
                # it to ``msg`` so the dispatch carries the
                # bolt-narration AND the prompt in one message —
                # same shape ``do_combat``'s SURVIVE-flee branch
                # uses.
                msg += await self.cancel_combat()

        if msg:
            Dispatcher.add(self.channel, parse(msg, monster))

    async def set_spawn_timer(self):
        r = randint(*self.spawn_timer_range)
        _log.debug(f"Setting spawn timer for {r} seconds.")
        self.game_clock.add_routine(self.do_spawn, r, True)

    def get_monster(self, monster: Optional[str] = None) -> bool:
        if monster is None:
            weather_patterns = (
                self.weather.active_patterns if self.weather is not None else None
            )
            self.monster = MonsterPlugin.get_random_monster(
                self.game_clock, weather=weather_patterns,
            )
            if self.monster is None:
                _log.debug("No monster available for current time of day; skipping spawn.")
                return False
            _log.debug(f"{self.monster} spawned randomly")
        else:
            # Exact stem / alias match first (fast path, unambiguous).
            # On miss, fall through to the fuzzy matcher so partial
            # names (``hyd``, ``math``) and abbreviations resolve when
            # they would have silently errored pre-refactor. Ambiguous
            # matches surface the candidate list so the operator can
            # pick explicitly.
            monster_cls = MonsterPlugin.get_plugin_class(monster)
            if monster_cls is None:
                candidates = MonsterPlugin.find_plugin_classes(monster)
                if len(candidates) == 1:
                    monster_cls = candidates[0]
                    _log.debug(
                        f"Fuzzy-resolved `{monster}` -> "
                        f"{monster_cls.__name__}"
                    )
                elif len(candidates) > 1:
                    display = ", ".join(
                        sorted(c.__module__.rsplit(".", 1)[-1] for c in candidates)
                    )
                    Dispatcher.add(
                        self.channel,
                        f"Did you mean one of: {display}? "
                        f"(`{monster}` matched {len(candidates)} monsters.)"
                    )
                    _log.debug(
                        f"Ambiguous monster query `{monster}` -> "
                        f"{display}"
                    )
                    return False
                else:
                    Dispatcher.add(self.channel, f"There is no such thing as a {monster}! (But there could be... 😈)")
                    _log.error(f"Monster definition not found for `{monster}`")
                    return False
            self.monster = monster_cls()
            _log.info(f"{self.monster} spawned administratively")

        embed, file = self.monster.get_embed()
        # Monster arrival templates may reference ``@2`` as a
        # witness / target player (e.g. pixie's "rifling through
        # @2's pocket", minotaur's "decided @2 look like a
        # problem"). Pass a random active-player so those tokens
        # render into a real name instead of silently falling back
        # to @1 and producing "rifling through pixie's pocket".
        arrival_args = self._build_witness_args(self.monster)
        Dispatcher.add(
            self.channel,
            parse(self.monster.arrival, *arrival_args),
            embed=embed, file=file,
        )
        # Body-parts table dispatched as a separate plain message so
        # it inherits full channel width (embeds render narrower and
        # wrap the Worn column). Caels' eye on 2026-04-26 confirmed
        # this is necessary for visible-loadout monsters.
        parts_table = self.monster.render_body_part_status_table(
            show_hp=False,
        )
        if parts_table:
            Dispatcher.add(self.channel, parts_table)
        # Populate the structural channel id before on_spawn so that
        # any override (or anything on_spawn dispatches to) can
        # already use the time façade. Keeps per-monster ``on_spawn``
        # focused on flavor / narrative, not plumbing.
        self.monster._channel_id = self.channel_id
        if spawn_msg := self.monster.on_spawn(self):
            Dispatcher.add(self.channel, parse(spawn_msg, *arrival_args))
        if self.monster.dies_from_time or self.monster.flees_from_time:
            self.game_clock.add_routine(self.check_time, 1)
        return True

    async def do_spawn(self, monster: Optional[str] = None):
        if self.monster:
            return

        if self.get_monster(monster):
            self.game_clock.add_routine(self.do_combat, self.spawn_duration, True)

    async def end_combat(self):
        """Thin delegator to :meth:`CombatState.end_combat`.

        The actual teardown (clearing monster / combatants / targets
        / looters and removing combat roles) lives on
        ``self.combat``; this method exists so existing callers that
        ``await game.end_combat()`` keep working and so the clock
        routine to remove is bound correctly (``self.do_combat``).
        """
        await self.combat.end_combat(
            self.player_manager, self.game_clock, self.do_combat,
        )

    async def _finalize_combat(self, outcome: str) -> str:
        """Universal end-of-combat shutdown: record the outcome,
        emit a loot-announce when the pool has anything in it,
        schedule ``loot_expires``, then run ``end_combat`` +
        ``set_spawn_timer``.

        Every code path that ends a fight calls this — flee
        (``cancel_combat`` from ``do_combat``'s escape branch or
        ``check_time``'s ``flees_from_time`` arm), death
        (``on_monster_death``), and any future trigger
        (surrender, magical disarmament, KO). Path-specific
        work (rolling death loot, corpse-scavenge sweep,
        path-specific narration / alt-text) stays in the caller;
        only the bits that are TRULY universal across every
        end-of-combat surface live here.

        Returns the loot-announce string (or empty string when
        there's nothing to announce). Callers decide where to
        render it relative to their own narration.

        :param outcome: ``"flee"`` or ``"death"``. Stored on
            ``self.last_combat_outcome`` so ``$loot`` can branch
            its wording (corpse vs. runaway).
        """
        self.last_combat_outcome = outcome
        has_loot = any(items for items in self.loot.values())
        announce = ""
        if has_loot:
            self.game_clock.add_routine(
                self.loot_expires, self.loot_duration, True,
            )
            announce = (
                f"\n{self.player_manager.roles[Roles.COMBAT_MAIN].mention}\n"
                f"There might be something to `{self.prefix}loot`..."
            )
        await self.end_combat()
        await self.set_spawn_timer()
        return announce

    async def cancel_combat(self) -> str:
        """Monster escapes — thin wrapper over
        :meth:`_finalize_combat` with ``outcome="flee"``.

        Mid-combat salvage that landed in ``self.loot`` (parts the
        players cleaved off before the monster bolted) stays —
        players keep what they earned. No fresh death-loot rolls
        here (nobody died); the death-loot pool simply doesn't
        roll, ``loot_expires`` cleans up uncollected items
        downstream, and the announce-string return lets callers
        thread the prompt into their own escape narration in the
        right rendering order.
        """
        return await self._finalize_combat(outcome="flee")

    async def loot_expires(self):
        """Cleans up uncollected loot and restarts spawning after loot expiration and minimum spawn time."""
        if any([len(loot) for loot in self.loot.values()]) > 0:
            Dispatcher.add(
                self.channel,
                "A swarm of tiny, shadow-clad creatures floods in and makes off with the items on the ground.",
            )
        self.loot.clear()

    async def on_monster_death(self) -> str:
        """Death-end of the combat lifecycle: roll fresh death
        loot, sweep undestroyed-part placements for corpse
        scavenge, then hand the universal shutdown sequence
        (announce + schedule + end + respawn) to
        :meth:`_finalize_combat`.

        ``self.loot[user_id]`` is initialized empty when a player
        joins combat (in ``_run_player_block``) and may already
        contain mid-combat salvage drops by the time death loot
        rolls. Death loot extends the same list rather than
        overwriting, so a player who farmed body parts during the
        fight keeps their salvage alongside whatever the corpse
        rolls.

        Corpse-scavenge: worn pieces on parts that were NEVER
        destroyed in combat get one final ``CORPSE_SCAVENGE_CHANCE``
        roll each (lower than per-part-destruction
        ``SALVAGE_SURVIVAL_CHANCE``). Without this, a clean
        one-hit-kill silently eats the visible "Wearing" gear from
        ``$look``. See ``project_armor_drop_on_clean_kill.md``."""

        # Corpse-scavenge sweep BEFORE the death-loot extends so the
        # narration ordering reads cleanly: scavenge lines first,
        # then the loot prompt. Pieces here are SPECIFIC INSTANCES
        # (not from a per-player fresh roll like ``get_loot``), so
        # we round-robin them across ``self.looters`` — every
        # surviving worn piece goes to exactly one looter, no
        # duplication. Pragmatic v1: ``on_monster_death`` doesn't
        # know which player landed the killing blow today, so
        # round-robin is the fair-distribution placeholder until a
        # last-hit-attribution channel exists. Killer-takes-all is a
        # natural future tightening.
        scavenge_lines: List[str] = []
        if self.monster is not None and self.looters:
            survivors = self.monster.get_corpse_scavenge()
            if survivors:
                owner_phrase = parse("@1np", self.monster)
                # Route each surviving instance to a looter (round-
                # robin) item-by-item. Narration is collapsed
                # per-part via :func:`_render_salvage_lines` so two
                # identical drops off the same part read as one
                # ``"Two ... slip free"`` line.
                per_part_items: "Dict[Any, List[Item]]" = {}
                for idx, (part, item) in enumerate(survivors):
                    recipient = self.looters[idx % len(self.looters)]
                    self.loot.setdefault(
                        recipient.user_id, [],
                    ).append(item)
                    per_part_items.setdefault(part, []).append(item)
                for part, items in per_part_items.items():
                    scavenge_lines.extend(
                        _render_salvage_lines(
                            items, owner_phrase, part.display_name,
                        )
                    )

        for player in self.looters:
            # ``setdefault`` defensively — the bucket should already
            # exist from ``_run_player_block``'s per-round assertion,
            # but if any future code path adds a player to
            # ``self.looters`` outside that pipeline, we'd crash here
            # without it. Cheap idempotent fallback.
            self.loot.setdefault(player.user_id, []).extend(
                self.monster.get_loot()
            )

        # Universal shutdown — outcome flag, has_loot announce
        # (computed BEFORE ``end_combat`` clears looters), schedule
        # ``loot_expires``, end_combat, set_spawn_timer.
        announce = await self._finalize_combat(outcome="death")

        # Death-specific message construction: announce when there's
        # loot, "nothing to loot" alt-text otherwise. Scavenge
        # narration prepends so the player sees what the death sweep
        # yielded above the loot prompt — same shape as the inline
        # salvage narration in ``_run_player_block``.
        msg = announce or "\nThere does not appear to be anything to loot, this time."
        if scavenge_lines:
            msg = "\n" + "\n".join(scavenge_lines) + msg
        return msg

    async def do_combat(self):
        """Phase-7 pipeline-driven round composer.

        Players attack in join order (``self.combatants`` forward),
        monster retaliates afterwards. Each attacker produces a
        :class:`CombatBlock`; the round-level output accumulates into
        a :class:`RoundOutput` whose named slots (player blocks,
        injury feedback, total-damage row, death narration, pre/post
        retaliation narration, escape) compose into the final
        Discord message via :meth:`RoundOutput.render`.

        The cyclops-style ordering bug — pre-retaliation flavor (the
        bellow that *causes* the wild swings) appearing below the
        wild-swing attack table — is fixed by slot order: the
        ``pre_retaliation_narration`` slot lands above the
        ``retaliation_table`` slot, with hydra-style state mutations
        staying in ``post_retaliation_narration`` below.

        The legacy monolithic body is preserved as
        :meth:`_do_combat_legacy` so a playtest regression can flip
        the call site in one line.
        """
        from caldanai.lib.rpg.combat.block import RoundOutput

        if self.monster is None:
            _log.error(f"Combat unable to proceed in `{self.guild.name}` because no monster was present.")
            await self.end_combat()
            await self.set_spawn_timer()
            return

        monster = self.monster
        round_output = RoundOutput()
        actual_body_damage = 0
        damage_by_player: Dict[int, Tuple[Player, int]] = {}
        death_msg = ""
        critical_part_kill = False
        health_before = monster.health

        # Phase 5 turn order: players in join order (replaces today's
        # reverse-of-join accident). Dead players get popped instead
        # of attacking. Iterating a copy so safe-remove stays safe.
        dead_idx: List[int] = []
        for i, player in enumerate(self.combatants):
            if player.is_dead():
                dead_idx.append(i)
                continue
            block = await self._run_player_block(player, monster)
            round_output.player_blocks.append(block)

            results = block.results
            player_damage = sum(
                r.damage for r in (results.all_results or []) if r.damage > 0
            ) if results is not None else 0
            player_res = (
                results.per_victim.get(monster) if results is not None else None
            )

            if player.user_id not in damage_by_player:
                damage_by_player[player.user_id] = (player, 0)
            _, prev = damage_by_player[player.user_id]
            damage_by_player[player.user_id] = (player, prev + player_damage)

            injury_chunk = ""
            if player_res is not None:
                if player_res.death_msg and not death_msg:
                    death_msg = player_res.death_msg
                if player_res.critical_part_kill:
                    critical_part_kill = True
                num_hits = player_res.num_hits
                if num_hits > 0 and not monster.is_dead():
                    final_body_dmg = _compute_body_hp_damage(
                        player_res, monster,
                    )
                    monster.health = max(0, monster.health - final_body_dmg)
                    actual_body_damage += final_body_dmg
                # Salvage drops for parts this player's resolution
                # destroyed. ``destroyed_parts`` is populated by
                # :func:`apply_sequence_to_target` and contains only
                # parts whose injury level transitioned to USELESS
                # this round. Last-hit attribution is implicit: the
                # part transitioned during THIS player's resolve, so
                # this player landed the destroying blow.
                #
                # ``get_salvage(part)`` returns a combined list:
                # actually-worn armor pieces from the part's
                # placements (each rolled against
                # ``SALVAGE_SURVIVAL_CHANCE``) plus generic
                # SALVAGE_DROPS harvest entries (rags, leather,
                # scale). Quality on worn pieces preserves the
                # spawn-time roll; SALVAGE_DROPS entries roll fresh.
                # Each rolled item gets an inline narration line
                # appended to the player's injury feedback so the
                # drop is visible *during* combat, not only at
                # post-combat ``$loot`` time.
                for destroyed in player_res.destroyed_parts:
                    salvage = monster.get_salvage(destroyed)
                    if not salvage:
                        continue
                    self.loot.setdefault(
                        player.user_id, [],
                    ).extend(salvage)
                    owner_phrase = parse("@1np", monster)
                    player_res.injury_feedback_lines.extend(
                        _render_salvage_lines(
                            salvage, owner_phrase, destroyed.display_name,
                        )
                    )
                if player_res.injury_feedback_lines:
                    injury_chunk = (
                        "\n".join(player_res.injury_feedback_lines) + "\n"
                    )
            round_output.injury_feedback.append(injury_chunk)

        # Remove dead combatants in reverse order so indices stay
        # valid. Matches the legacy ``combatants.pop(i)`` semantics.
        for i in reversed(dead_idx):
            self.combatants.pop(i)

        # Part-driven death check — same priority as legacy: more
        # specific than the HP-zero fallback.
        if not death_msg:
            part_death_msg = monster.check_part_driven_death()
            if part_death_msg:
                death_msg = part_death_msg
                critical_part_kill = True

        if not death_msg and monster.is_dead():
            death_msg = monster.death if hasattr(monster, 'death') else ""

        if not critical_part_kill:
            remaining = 0 if monster.is_dead() else max(health_before - actual_body_damage, 0)
            round_output.total_damage_row = (
                f"Total damage done vs Health:\n{_INDENT}{actual_body_damage:,} vs {health_before:,} "
                f"= **{remaining} health remaining.**\n"
            )

        round_output.death_narration = parse(death_msg, monster)

        if monster.is_dead():
            self.monster_statics[f"{monster.name}.killed"] += 1
            round_output.loot_hint = parse(await self.on_monster_death(), monster)
            msgs = Dispatcher.split_message(round_output.render(), "```\n", True)
            for m in msgs:
                Dispatcher.add(self.channel, m)
            return

        # Monster retaliation block — their turn in the new turn order.
        # ``on_pre_retaliation`` runs before ``attack_random`` so the
        # rage / desperation / transformation announcement lands above
        # the table it explains; ``on_combat_round`` runs after for
        # state-mutation hooks (hydra regrowth) whose narration belongs
        # below the attack table.
        if self.combatants and (
            monster.aggression & (AggressionLevels.RAMPAGE | AggressionLevels.VENGEFUL | AggressionLevels.SURVIVE)
        ):
            damage_pairs = list(damage_by_player.values())
            round_output.pre_retaliation_narration = (
                monster.on_pre_retaliation(damage_pairs) or ""
            )
            # Unconditional assignment preserves legacy output shape
            # even when attack_random returns "" — the slot's leading
            # newline in render() still lands the same separator.
            round_output.retaliation_table = monster.attack_random(self.combatants)
            round_output.post_retaliation_narration = (
                monster.on_combat_round(damage_pairs) or ""
            )

            if monster.aggression & AggressionLevels.RAMPAGE or (
                monster.aggression & AggressionLevels.SURVIVE and monster.get_health_scale() > 0.1
            ):
                Dispatcher.add(self.channel, round_output.render())
                self.combatants.clear()
                self.combat_targets.clear()
                self.game_clock.add_routine(self.do_combat, int(self.spawn_duration / 2), True)
                return

        if (
            not self.combatants
            or monster.aggression in (AggressionLevels.VENGEFUL, AggressionLevels.PASSIVE)
            or (monster.aggression & AggressionLevels.SURVIVE and monster.get_health_scale() <= 0.1)
        ):
            self.monster_statics[f"{monster.name}.escaped"] += 1
            round_output.escape_narration = parse(
                monster.escape, *self._build_witness_args(monster),
            )
            # ``cancel_combat`` returns the loot-announce text when
            # there's mid-combat salvage in the pool; append it to
            # the escape narration so it renders AFTER the bolt
            # line (``loot_hint`` slot lands before
            # ``escape_narration`` in ``RoundOutput.render`` —
            # right order for death, backwards for flee).
            announce = await self.cancel_combat()
            if announce:
                round_output.escape_narration += announce
            Dispatcher.add(self.channel, round_output.render())

    async def _run_player_block(
        self,
        player: "Player",
        monster: "MonsterPlugin",
    ) -> "CombatBlock":
        """Execute one player's attacker-block via the combat pipeline
        stages and return the populated :class:`CombatBlock`.

        Phase 6d port — player combat runs through
        ``pick_actions`` → ``pick_targets`` → ``resolve`` →
        ``render_table`` → ``narrate_results`` just like every monster
        plugin's :meth:`attack_random`. ``Player.pick_actions`` returns
        the equipment-aware source list; explicit part-targeting from
        ``$kill arm.left leg.right`` / ``$target`` is resolved into
        coupled ``(monster, part)`` assignments up front, so the
        default ``pick_targets`` routing honors them the same way
        legacy ``do_attack`` did. Body-HP application with the
        ``max(num_hits, total - defense)`` floor stays the composer's
        responsibility (Phase 6a moved it out of ``Creature.resolve``).

        Phase 7 wired the block as the actual return value (it was
        constructed and discarded before, with the caller taking a
        ``(msg, damage, resolution)`` tuple). Callers derive those
        three from the block: ``block.table`` is the message,
        ``block.results.per_victim[monster]`` is the resolution, and
        ``sum(r.damage for r in block.results.all_results if r.damage
        > 0)`` is the damage tally.
        """
        from caldanai.lib.rpg.combat.block import Assignment, CombatBlock
        from random import choice as _choice

        player.health_regen = 0
        if player not in self.looters:
            await self.player_manager.set_player_combatant(player)
            self.looters.append(player)
        # Re-assert the loot bucket every round, not just on first
        # join: ``loot_expires`` is a clock routine that fires
        # ``self.loot.clear()`` after a delay, and the delay is
        # scheduled by the PREVIOUS combat's death. If it fires
        # mid-fight (between rounds of the next combat), the bucket
        # we set up at first-join gets wiped — and ``self.looters``
        # still has the player, so the join-time branch above
        # doesn't re-run. Without this re-assertion, the next
        # ``self.loot[player.user_id]`` access (salvage extend
        # below, or death-loot extend in ``on_monster_death``)
        # KeyErrors and crashes the round mid-resolve.
        self.loot.setdefault(player.user_id, [])

        actions = player.pick_actions()
        explicit_targets = self.combat_targets.get(player.user_id)

        # Pre-resolve explicit part names into concrete parts, then
        # build tuple-form assignments so ``Creature.resolve`` routes
        # damage to the chosen part. Mirrors ``Creature.do_attack``'s
        # indexing (one name → all sources, N names → source[i] cycles
        # mod N).
        explicit_parts: "List[Optional[object]]" = []
        if explicit_targets and monster.body_parts:
            for name in explicit_targets:
                matches = monster.find_parts(name)
                explicit_parts.append(_choice(matches) if matches else None)

        assignments: "List[Assignment]" = []
        if actions:
            if explicit_parts:
                for i, source in enumerate(actions):
                    resolved = explicit_parts[i % len(explicit_parts)]
                    if resolved is not None and not resolved.is_destroyed():
                        assignments.append(
                            Assignment(source=source, target=(monster, resolved)),
                        )
                    else:
                        assignments.append(
                            Assignment(source=source, target=monster),
                        )
            else:
                assignments = player.pick_targets(actions, [monster])

        results = player.resolve(assignments)
        table = player.render_table(results)
        result_lines = player.narrate_results(results)

        return CombatBlock(
            attacker=player,
            actions=list(actions),
            assignments=list(assignments),
            results=results,
            table=table or None,
            result_narratives=list(result_lines),
        )

    async def _do_combat_legacy(self):
        """Pre-Phase-5 monolithic combat loop. Preserved so a regression
        can revert the ``do_combat`` call site in one line — the
        design-doc Phase 7/8 cleanup deletes this after parity
        stabilizes in playtest.
        """

        if self.monster is None:
            _log.error(f"Combat unable to proceed in `{self.guild.name}` because no monster was present.")
            await self.end_combat()
            await self.set_spawn_timer()
            return

        monster = self.monster
        msg = ""
        damage = 0
        actual_body_damage = 0
        damage_by_player = {}
        death_msg = ""
        critical_part_kill = False
        health_before = monster.health

        for i in range(len(self.combatants) - 1, -1, -1):
            player = self.combatants[i]
            if not player.is_dead():
                player.health_regen = 0
                if player not in self.looters:
                    await self.player_manager.set_player_combatant(player)
                    self.looters.append(player)
                explicit_targets = self.combat_targets.get(player.user_id)
                sequence = player.do_attack(self.monster, explicit_part_names=explicit_targets)
                msg += sequence.to_markdown()
                d = sequence.total_damage()
                damage += d
                if player.user_id not in damage_by_player:
                    damage_by_player[player.user_id] = (player, 0)
                _, prev = damage_by_player[player.user_id]
                damage_by_player[player.user_id] = (player, prev + d)

                # Per-result part routing + coalesced injury feedback +
                # part-side hook firing live in ``apply_sequence_to_target``.
                # The helper auto-infers ``attacker`` from the sequence;
                # the player-attacks-monster asymmetry is preserved by
                # the hook's ``hasattr`` gate (Players don't define
                # ``on_target_part_destroyed``), so we don't need to
                # pass an explicit override here.
                resolution = apply_sequence_to_target(sequence, monster)
                if resolution.death_msg and not death_msg:
                    death_msg = resolution.death_msg
                # Sticky OR across per-player resolutions: if any
                # sequence killed the monster by destroying a critical
                # part, suppress the HP summary at the end regardless
                # of which sequence did the deed.
                if resolution.critical_part_kill:
                    critical_part_kill = True

                # Defense subtracted once from the per-player total
                # (variant B — restored pre-refactor balance).
                # num_hits is the minimum damage floor (dual-wield = 2, single = 1).
                num_hits = resolution.num_hits
                if num_hits > 0 and not monster.is_dead():
                    final_body_dmg = _compute_body_hp_damage(
                        resolution, monster,
                        results=sequence.results,
                    )
                    monster.health = max(0, monster.health - final_body_dmg)
                    actual_body_damage += final_body_dmg

                if resolution.injury_feedback_lines:
                    msg += "\n".join(resolution.injury_feedback_lines) + "\n"
            else:
                self.combatants.pop(i)

        # Part-state-driven death check (e.g. hydra with zero live
        # heads) runs BEFORE the generic HP-zero fallback below so
        # that when both conditions fire in the same round — last
        # head destroyed AND body HP depleted — the more-specific
        # decapitation narration wins over the bleed-out default.
        # Also avoids the post-death retaliation swing and round-
        # late ``$loot`` hint the prior ``on_combat_round``-based
        # detection produced. Hook zeroes ``self.health`` when it
        # fires; we treat it as a critical-part kill so the HP
        # summary doesn't print a confusing "0 vs X remaining"
        # after.
        if not death_msg:
            part_death_msg = monster.check_part_driven_death()
            if part_death_msg:
                death_msg = part_death_msg
                critical_part_kill = True

        # Generic HP-zero fallback — fires only if no more-specific
        # death narration was set by a critical-part destruction
        # (via ``resolution.death_msg``) or by the part-driven hook
        # above. Moved out of the player-attack loop so the
        # priority ordering is explicit.
        if not death_msg and monster.is_dead():
            death_msg = monster.death if hasattr(monster, 'death') else ""

        # Skip the HP summary if the creature died from a critical
        # part destruction — the "utterly destroyed" feedback + death
        # message already tells the story, and "0 vs 117 = 0 health
        # remaining" is confusing noise. Signal comes directly from
        # ``apply_sequence_to_target`` rather than the old arithmetic
        # inference (``actual_body_damage < health_before``), which
        # false-positived against any kill path that didn't route
        # through body HP (status ticks, magic bypass, partless-
        # creature double-damage bug).
        if not critical_part_kill:
            remaining = 0 if monster.is_dead() else max(health_before - actual_body_damage, 0)
            msg += (
                f"Total damage done vs Health:\n{_INDENT}{actual_body_damage:,} vs {health_before:,} "
                f"= **{remaining} health remaining.**\n"
            )

        msg += parse(death_msg, monster)
        if monster.is_dead():
            self.monster_statics[f"{monster.name}.killed"] += 1
            msg += parse(await self.on_monster_death(), monster)
            msgs = Dispatcher.split_message(msg, "```\n", True)
            for m in msgs:
                Dispatcher.add(self.channel, m)

        else:
            if self.combatants and (
                monster.aggression & (AggressionLevels.RAMPAGE | AggressionLevels.VENGEFUL | AggressionLevels.SURVIVE)
            ):

                # Retaliate FIRST with current heads/sources, THEN run
                # the combat-round hook (hydra regrowth, doppelganger
                # re-imitation, etc.). New heads spawned by regrowth
                # should NOT attack the same turn they grow.
                msg += f"\n{monster.attack_random(self.combatants)}"
                if round_msg := monster.on_combat_round(list(damage_by_player.values())):
                    msg += f"\n{round_msg}"

                if monster.aggression & AggressionLevels.RAMPAGE or (
                    monster.aggression & AggressionLevels.SURVIVE and monster.get_health_scale() > 0.1
                ):
                    Dispatcher.add(self.channel, msg)
                    self.combatants.clear()
                    self.combat_targets.clear()
                    self.game_clock.add_routine(self.do_combat, int(self.spawn_duration / 2), True)
                    return

            if (
                not self.combatants
                or monster.aggression in (AggressionLevels.VENGEFUL, AggressionLevels.PASSIVE)
                or (monster.aggression & AggressionLevels.SURVIVE and monster.get_health_scale() <= 0.1)
            ):
                self.monster_statics[f"{monster.name}.escaped"] += 1
                Dispatcher.add(
                    self.channel,
                    f"{msg}\n{parse(monster.escape, *self._build_witness_args(monster))}",
                )
                await self.cancel_combat()

    async def kill_monster(self):
        """Admin kill — forces monster death with NO loot reward.

        Deliberately bypasses :meth:`_finalize_combat` and the
        whole loot pipeline (death-loot rolls, corpse-scavenge,
        the announce + ``loot_expires`` schedule). Admin kills
        aren't real combat — letting them drop loot would let
        operators manufacture armor by spamming ``$spawn kill``,
        and the announce prompt would be a confusing UI artifact
        for what is mechanically just "make this monster go away."

        ``self.loot.clear()`` wipes any mid-combat salvage that
        landed before the admin kill — players who chopped a leg
        off the bandit before the operator killed it lose that
        salvage. Acceptable trade for "admin kill is a clean
        despawn"; if a future operator workflow wants the loot
        preserved, that's a deliberate design decision worth a
        memo before changing this. (Caels confirmed 2026-04-27.)

        ``$spawn destroy`` is a separate admin path that DOES
        let drops happen — it's the testing path for verifying
        salvage / loadout / scavenge mechanics work end-to-end.
        Don't conflate the two.
        """
        monster = self.monster
        self.loot.clear()
        await self.end_combat()
        await self.set_spawn_timer()
        if monster:
            msg = parse(monster.death or "", monster)
            if msg:
                Dispatcher.add(self.channel, msg)

    async def do_ambience(self):
        """Small chance to display a random flavor ambience message.

        Sunrise/sunset transition narration used to also flow through
        here; it now lives on a dedicated ``CelestialDaemon``
        scheduled directly on the clock. This method is the random
        flavor-choice roll only — kill-switch guard + the roll.

        Gated by the ``local`` ambience subsystem, which ANDs with
        the master ``enable_ambience``. Toggling either off self-
        removes this routine the next time it fires.
        """

        if not self.ambience_enabled("local"):
            _log.info(f"Removing ambience loop for game on {self.guild.name}.")
            self.game_clock.remove_routine(self.do_ambience)
            return

        if random.randint(1, 3000) != 3000:
            return

        msg = choice(
            [
                "A squirrel bounds across the ground, and up a nearby tree.",
                "A bush rustles as something skitters unseen within.",
                f"A lonesome howl floats in from the {get_random_direction()}.",
                "Happy warbling resounds as a songbird flits across the area.",
                f"A pack of wolves serenades from the {get_random_direction()}.",
                "At the edge of the wood-line, a bear trundles about curiously for a moment before disappearing into"
                " the trees.",
                "The ground trembles slightly for a moment, though whether from earthquake or monstrosity is"
                " impossible to determine.",
                "A choir of insectile sound rises, thousands of tiny voices calling out to each other.",
                f"A {choice('gentle|strong|slow|light|moderate'.split('|'))} breeze stirs the area, bringing the"
                f" scent of {choice('the sea|dust|pine|animal musk|death'.split('|'))} with it.",
                "Some unknown creature blazes a trail throughout the tall grasses nearby.",
            ]
        )

        Dispatcher.add(self.channel, msg)

    def to_dict(self):
        """Returns the database friendly dictionary for this game."""

        d = {
            "guild_id": self.guild.id,
            "channel_id": self.channel.id,
            "use_spawn_timer": self.use_spawn_timer,
            "spawn_duration": int(self.spawn_duration / 60),
            "loot_duration": int(self.loot_duration / 60),
            "spawn_timer_range": list(self.spawn_timer_range),
            "enable_ambience": self.enable_ambience,
            "enable_ambience_local": self.enable_ambience_local,
            "enable_ambience_celestial": self.enable_ambience_celestial,
            "enable_ambience_weather": self.enable_ambience_weather,
            "game_time": self.game_clock.get_seconds(),
        }

        if self.weather is not None:
            d["weather"] = self.weather.to_dict()

        if self.id is not None:
            d["_id"] = self.id

        return d

    # Adds or updates a game object in the database.
    def save(self) -> None:
        """Adds or updates a game object in the database."""

        try:
            DB.update_game(
                self.guild.id, self.channel.id, self.to_dict(), upsert=True,
            )
            if self.id is None:
                game = DB.get_game(self.guild.id, self.channel.id)
                self.id = game["_id"] if game else None
        except Exception as e:
            _log.error(e)

    @classmethod
    async def load(cls, guild_id: int, channel_id: int, bot: "Bot") -> Optional["Game"]:
        """Returns the game on ``(guild_id, channel_id)`` loaded from
        the database, or ``None`` if no such game exists."""

        if guild_id is None or channel_id is None:
            return None

        try:
            g = DB.get_game(guild_id, channel_id)
            if g is None or bot is None:
                return None

            return await Game.from_dict(g, bot)

        except Exception as e:
            _log.error(e)
            return None

    @classmethod
    async def from_dict(cls, d: dict, bot: "Bot") -> Optional["Game"]:
        """Returns a game from it's dictionary representation."""

        if d is None or bot is None:
            return None

        game = cls(
            bot=bot,
            game_id=d["_id"],
            use_spawn_timer=d["use_spawn_timer"],
            spawn_range=tuple(d["spawn_timer_range"]),
            spawn_duration=int(d["spawn_duration"]),
            loot_duration=int(d["loot_duration"]),
            enable_ambience=d["enable_ambience"],
            # Per-subsystem flags default to True (opt-in parity
            # with the master-only behavior) so pre-split documents
            # load without surprise suppression.
            enable_ambience_local=d.get("enable_ambience_local", True),
            enable_ambience_celestial=d.get("enable_ambience_celestial", True),
            enable_ambience_weather=d.get("enable_ambience_weather", True),
            game_time=d["game_time"],
        )

        game.guild = bot.get_guild(d["guild_id"])
        game.channel = bot.get_channel(d["channel_id"])
        # Keep PlayerManager's dispatch target in sync with the newly
        # resolved channel. ``__init__`` ran with ``channel=None`` on
        # the load path so the manager still holds the None default
        # until now — update it before any routine (e.g. health
        # regen) has a chance to fire and silently skip dispatch.
        game.player_manager.channel = game.channel
        # GameClock was constructed with channel=None (same load-
        # path reason above), leaving its ``_channel_id`` as
        # ``None``. Every tick then stamped ``channel_log_context(None)``
        # and the per-game log prefix never appeared for loaded
        # games — even though freshly-created games worked fine.
        # Patch it now that the channel resolved.
        if game.channel is not None:
            game.game_clock._channel_id = game.channel.id

        if game.guild is None:
            _log.error(f"Failed to load game {d['_id']}: guild {d['guild_id']} not found.")
            return None
        if game.channel is None:
            _log.error(f"Failed to load game {d['_id']}: channel not found for guild {d['guild_id']}.")
            return None

        # Now that channel is bound, register with channel routing
        # and spin up the weather daemon with persisted state.
        # ``__init__`` skipped this path because ``channel`` wasn't
        # supplied to the constructor on the load path.
        # ``GameClock.for_channel`` resolves through the same routing
        # map, so there is no separate clock registration step.
        from caldanai.lib.rpg.helpers.enums import Seasons
        game.register_channel(game.channel.id)
        game.weather = WeatherDaemon(game.channel.id)
        game.celestial = CelestialDaemon(game.channel.id)
        if d.get("weather"):
            game.weather.load_dict(d["weather"])
        if game.ambience_enabled("weather"):
            game.weather.start(Seasons(game.game_clock.get_season()))
        if game.ambience_enabled("celestial"):
            game.celestial.start()

        await game.player_manager.load_players(game.guild, game.channel.id)
        game.game_clock.add_routine(game.player_manager.update_inactive_roles, 3600)
        game.prefix = DB.get_server_by_guild_id(game.guild.id)["prefix"]

        # Kickstart regen for dead players so they don't waste the first cycle
        dead_count = 0
        for player in game.player_manager.players.values():
            if player.is_dead():
                dead_count += 1
                if player.health_regen == 0:
                    player.health_regen = 1
        if dead_count:
            _log.info(f"Game {game.guild.name}: {dead_count} dead player(s) — health regen will revive them.")

        return game
