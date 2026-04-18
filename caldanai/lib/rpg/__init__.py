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
from caldanai.lib.rpg.combat.resolution import apply_sequence_to_target
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
        self.use_spawn_timer = use_spawn_timer
        self.spawn_duration = spawn_duration * 60
        self.loot_duration = loot_duration * 60
        self.loot_countdown = loot_duration * 60
        self.spawn_timer_range = spawn_range
        self.enable_ambience = enable_ambience
        self.enable_ambience_local = enable_ambience_local
        self.enable_ambience_celestial = enable_ambience_celestial
        self.enable_ambience_weather = enable_ambience_weather
        self.game_clock = GameClock(game_time=game_time)
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
            _log.debug(f"Game clock starting for {game_id}")
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
                await self.cancel_combat()

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
            # Registry lookup replaces the old per-call filesystem glob
            # + importlib scan. Every monster plugin is already loaded
            # at startup via ``MonsterPlugin.load_plugins``; matching by
            # filename stem (case-insensitive) preserves the exact name
            # set the old glob accepted (``goblin``, ``math_teacher``,
            # ``GOBLIN`` all still resolve).
            monster_cls = MonsterPlugin.get_plugin_class(monster)
            if monster_cls is None:
                Dispatcher.add(self.channel, f"There is no such thing as a {monster}! (But there could be... 😈)")
                _log.error(f"Monster definition not found for `{monster}`")
                return False
            self.monster = monster_cls()
            _log.debug(f"{self.monster} spawned selectively")

        embed, file = self.monster.get_embed()
        Dispatcher.add(self.channel, parse(self.monster.arrival, self.monster), embed=embed, file=file)
        # Populate the structural channel id before on_spawn so that
        # any override (or anything on_spawn dispatches to) can
        # already use the time façade. Keeps per-monster ``on_spawn``
        # focused on flavor / narrative, not plumbing.
        self.monster._channel_id = self.channel_id
        if spawn_msg := self.monster.on_spawn(self):
            Dispatcher.add(self.channel, parse(spawn_msg, self.monster))
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

    async def cancel_combat(self):
        """Monster escapes — no loot, full combat cleanup."""
        self.loot.clear()
        await self.end_combat()
        await self.set_spawn_timer()

    async def loot_expires(self):
        """Cleans up uncollected loot and restarts spawning after loot expiration and minimum spawn time."""
        if any([len(loot) for loot in self.loot.values()]) > 0:
            Dispatcher.add(
                self.channel,
                "A swarm of tiny, shadow-clad creatures floods in and makes off with the items on the ground.",
            )
        self.loot.clear()

    async def on_monster_death(self) -> str:
        """Generates loot, ends combat, and sets up respawn."""
        has_loot = False
        for player in self.looters:
            loot = self.monster.get_loot()
            if len(loot) > 0:
                has_loot = True
            self.loot[player.user_id] = loot

        await self.end_combat()
        await self.set_spawn_timer()

        if has_loot:
            self.game_clock.add_routine(self.loot_expires, self.loot_duration, True)
            msg = (
                f"\n{self.player_manager.roles[Roles.COMBAT_MAIN].mention}\nThere might be something to "
                f"`{self.prefix}loot`..."
            )
        else:
            msg = "\nThere does not appear to be anything to loot, this time."
        return msg

    async def do_combat(self):
        """Tallies and displays combat results."""

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
        # Snapshot health before any per-result damage is applied so the
        # "Total damage done vs Health" summary line stays accurate.
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
                # The helper does NOT fire the attacker-side
                # ``on_target_part_destroyed`` hook here — the player
                # path has no such hook by design, and passing
                # ``attacker=None`` makes that asymmetry explicit.
                resolution = apply_sequence_to_target(sequence, monster)
                if resolution.death_msg and not death_msg:
                    death_msg = resolution.death_msg

                # Defense subtracted once from the per-player total
                # (variant B — restored pre-refactor balance).
                # num_hits is the minimum damage floor (dual-wield = 2, single = 1).
                num_hits = resolution.num_hits
                if num_hits > 0 and not monster.is_dead():
                    defense = monster.get_defense()
                    final_body_dmg = max(num_hits, resolution.body_damage_total - defense)
                    monster.health = max(0, monster.health - final_body_dmg)
                    actual_body_damage += final_body_dmg
                    if monster.health == 0 and not death_msg:
                        death_msg = monster.death if hasattr(monster, 'death') else ""

                if resolution.injury_feedback_lines:
                    msg += "\n".join(resolution.injury_feedback_lines) + "\n"
            else:
                self.combatants.pop(i)

        # Skip the HP summary if the creature died from a critical part
        # destruction — the "utterly destroyed" feedback + death message
        # already tells the story, and "0 vs 117 = 0 health remaining"
        # is confusing noise.  Detect by checking if the body damage we
        # dealt wasn't enough to kill on its own.
        critical_kill = monster.is_dead() and actual_body_damage < health_before
        if not critical_kill:
            remaining = 0 if monster.is_dead() else max(health_before - actual_body_damage, 0)
            msg += (
                f"Total damage done vs Health:\n\u2800\u2800\u2800\u2800{actual_body_damage:,} vs {health_before:,} "
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
                Dispatcher.add(self.channel, f"{msg}\n{parse(monster.escape, monster)}")
                await self.cancel_combat()

    async def kill_monster(self):
        """Admin kill — forces monster death with no loot."""
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
            _log.debug(f"Removing ambience loop for game on {self.guild.name}.")
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
