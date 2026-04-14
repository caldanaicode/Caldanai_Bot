import asyncio
import inspect
import importlib
import random
from glob import glob
from os import path

from discord import Guild, TextChannel
from typing import Any, Callable, Dict, List, Tuple, Union, Optional, TYPE_CHECKING
from random import choice, randint

from caldanai.lib.rpg.helpers.enums import AggressionLevels, InjuryLevels, TimesOfDay, Roles
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.areas import Area
from caldanai.lib.rpg.time import GameClock
from caldanai.lib.rpg.helpers import get_random_direction
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
        :param enable_ambience: Whether to display ambience messages such as weather, day/night cycles,    and monster ambience messages.
        :param game_time: The game's internal time value.
        """
        self.bot = bot
        self.id = game_id
        self.guild = guild
        self.channel = channel
        self.player_manager: PlayerManager = PlayerManager()
        self.monster: Optional[MonsterPlugin] = None
        self.monsters: List[str] = []
        self.combatants: List[Player] = []
        self.combat_targets: Dict[int, Optional[str]] = {}
        self.looters: List[Player] = []
        self.loot: Dict[int, List[Union[Item, Weapon]]] = {}
        self.use_spawn_timer = use_spawn_timer
        self.spawn_duration = spawn_duration * 60
        self.loot_duration = loot_duration * 60
        self.loot_countdown = loot_duration * 60
        self.spawn_timer_range = spawn_range
        self.enable_ambience = enable_ambience
        self.game_clock = GameClock(game_time=game_time)
        self.weather = None
        self._last_ambience_tick = self.game_clock.get_seconds()
        self.room0: Area = None
        self.monster_statics: Dict[str, int] = {}

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
            self.game_clock.add_routine(self.do_health_regen, 1800 / self.game_clock.time_scale)

        if use_spawn_timer:
            self.game_clock.add_routine(self.set_spawn_timer, 5, True)
        if enable_ambience:
            self.game_clock.add_routine(self.do_ambience, 1)

        self.bot = bot
        if bot and guild:
            bot.games[self.guild.id] = self

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
                key = f"{self.monster.name}.fled"
                self.monster_statics[key] = (
                    1 if key not in self.monster_statics.keys() else self.monster_statics[key] + 1
                )
                await self.cancel_combat()

        if msg:
            Dispatcher.add(self.channel, parse(msg, monster))

    async def set_spawn_timer(self):
        await self.player_manager.clear_combat_roles()
        r = randint(*self.spawn_timer_range)
        _log.debug(f"Setting spawn timer for {r} seconds.")
        self.game_clock.add_routine(self.do_spawn, r, True)

    def get_monster(self, monster: Optional[str] = None) -> bool:
        if monster is None:
            self.monster = MonsterPlugin.get_random_monster(self.game_clock)
            if self.monster is None:
                _log.debug("No monster available for current time of day; skipping spawn.")
                return False
            _log.debug(f"{self.monster} spawned randomly")
        else:
            available_monsters = [
                filepath.split(path.sep)[-1][:-3].lower()
                for filepath in glob("./caldanai/lib/rpg/creatures/monsters/*.py")
            ]
            available_monsters.remove("__init__")
            if monster.lower() in available_monsters:
                mod = importlib.import_module(f"caldanai.lib.rpg.creatures.monsters.{monster}")
                # Find the MonsterPlugin subclass defined in this module
                monster_cls = next(
                    (
                        obj for obj in vars(mod).values()
                        if isinstance(obj, type) and issubclass(obj, MonsterPlugin) and obj is not MonsterPlugin
                    ),
                    None,
                )
                if monster_cls is None:
                    Dispatcher.add(self.channel, f"The {monster} module does not define a monster class.")
                    _log.error(f"No MonsterPlugin subclass found in module `{monster}`")
                    return False
                self.monster = monster_cls()
                _log.debug(f"{self.monster} spawned selectively")
            else:
                Dispatcher.add(self.channel, f"There is no such thing as a {monster}! (But there could be... 😈)")
                _log.error(f"Monster definition not found for `{monster}`")
                return False

        embed, file = self.monster.get_embed()
        Dispatcher.add(self.channel, parse(self.monster.arrival, self.monster), embed=embed, file=file)
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

    async def cancel_combat(self):
        """Clears the current monster, combatants, and loot."""
        self.monster = None
        self.combatants.clear()
        self.combat_targets.clear()
        self.loot.clear()
        self.looters.clear()
        self.game_clock.remove_routine(self.do_combat)
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
        """Generates loot, shows monster death, and clears combatants."""
        has_loot = False
        for player in self.looters:
            loot = self.monster.get_loot()
            if len(loot) > 0:
                has_loot = True
            self.loot[player.user_id] = loot

        self.monster = None
        self.combatants.clear()
        self.combat_targets.clear()
        self.looters.clear()
        self.game_clock.remove_routine(self.do_combat)

        if has_loot:
            self.game_clock.add_routine(self.loot_expires, self.loot_duration, True)
            await self.set_spawn_timer()
            msg = (
                f"\n{self.player_manager.roles[Roles.COMBAT_MAIN].mention}\nThere might be something to "
                f"`{self.prefix}loot`..."
            )
        else:
            await self.set_spawn_timer()
            msg = "\nThere does not appear to be anything to loot, this time."
        return msg

    async def do_health_regen(self):
        """Applies per-tick health regen to players.

        Body HP regenerates as before. In addition — until we build a
        dedicated part-healing mechanic (potions / shrines / skills) —
        the single most-injured body part also receives the regen
        amount each tick, clamped to its max. This keeps players from
        being permanently trapped after a maiming without making every
        injury trivially self-heal: the regen amount starts at 0,
        ramps by 1 per tick, and resets only when every part and body
        HP are back to full. Silent on the part side (no narration per
        tick) to avoid spam; the returned body-HP resurrection message
        is still emitted.
        """
        msg = ""
        for player in self.player_manager.players.values():
            max_health = player.get_health_max()
            body_needs = player.health < max_health

            if body_needs:
                m = player.apply_damage(-player.health_regen)
                if m:
                    msg += f"\n{m}"

            injured_part = self._most_injured_part(player)
            if injured_part is not None:
                # Snapshot before healing so we can detect a level
                # transition (SEVERE → MODERATE, USELESS → SEVERE,
                # etc.) and narrate the recovery.
                old_level = injured_part.get_injury_level()
                injured_part.apply_damage(-player.health_regen)
                new_level = injured_part.get_injury_level()
                if new_level != old_level:
                    template = injured_part.get_recovery_string()
                    if template:
                        # Parse through the @ system so pronouns /
                        # names come out naturally (e.g. "Caels winces
                        # as feeling returns to her left arm.").
                        line = parse(template, player)
                        msg += f"\n{line[0].upper()}{line[1:]}"

            # Regen grows until all of the player's HP pools (body +
            # every part) are back at max, then resets. Ramp is +2
            # per tick so heavy injuries catch up in a reasonable
            # session window (~75 real-minutes for a full-body heal
            # at ~100 HP).
            any_injury = (
                player.health < max_health
                or any(
                    p.health < p.health_max
                    for p in (player.body_parts or [])
                )
            )
            player.health_regen = (player.health_regen + 2) if any_injury else 0

        if msg:
            Dispatcher.add(self.channel, msg)

    @staticmethod
    def _most_injured_part(player):
        """Return the body part with the lowest health/health_max
        ratio, or None if all parts are at max health. Used by
        ``do_health_regen`` to triage: healing flows to the most
        damaged part first so a destroyed limb recovers before
        cosmetic bruises."""
        parts = player.body_parts or []
        injured = [p for p in parts if p.health < p.health_max]
        if not injured:
            return None
        return min(injured, key=lambda p: p.health / p.health_max)

    async def do_combat(self):
        """Tallies and displays combat results."""

        if self.monster is None:
            _log.error(f"Combat unable to proceed in `{self.guild.name}` because no monster was present.")
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
                    # TODO: This may need to be disabled because the role cannot be reliably removed after combat.
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

                # Per-result: route raw (pre-defense) damage to parts for
                # injury tracking. Body HP is handled AFTER all sources
                # resolve, with defense subtracted once from the total.
                #
                # Injury-message coalescing: when multiple sources in a
                # sequence (e.g. dual-wield) target the same part, we
                # snapshot that part's starting level ONCE before any
                # hits land and emit a single transition message after
                # all hits resolve. This avoids the dual-wield chatter
                # of "lightly battered" followed by "utterly destroyed"
                # for a single attack action.
                injury_feedback = []
                num_hits = 0
                part_starting_levels: dict = {}  # id(part) -> (part, old_level)
                for result in sequence.results:
                    if result.damage > 0:
                        num_hits += 1
                        part = result.target_part
                        if part is not None and id(part) not in part_starting_levels:
                            part_starting_levels[id(part)] = (part, part.get_injury_level())

                        dmg_result = monster.apply_damage(
                            result.damage,
                            dmg_type=result.dmg_type,
                            target_part=part,
                        )
                        if dmg_result and not death_msg:
                            death_msg = dmg_result

                # Emit one injury message per unique part based on the
                # level transition across the full sequence.
                # ``apply_damage`` intentionally does NOT fire the hooks
                # itself — this is the single authoritative call site
                # for ``on_injury_change`` and ``on_destroyed`` so hooks
                # with side effects (wing grounding, pain cries) fire
                # exactly once per attack action per part.
                for part, old_level in part_starting_levels.values():
                    new_level = part.get_injury_level()
                    if new_level == old_level:
                        continue
                    if new_level != InjuryLevels.NONE:
                        feedback = part.get_injury_string()
                        injury_feedback.append(f"   {feedback[0].upper()}{feedback[1:]}")
                    hook_msg = part.on_injury_change(monster, old_level, new_level)
                    if hook_msg:
                        injury_feedback.append(f"   {hook_msg}")
                    # First-time destruction: fire on_destroyed once.
                    if (
                        new_level == InjuryLevels.USELESS
                        and old_level != InjuryLevels.USELESS
                    ):
                        destroyed_msg = part.on_destroyed(monster)
                        if destroyed_msg:
                            injury_feedback.append(f"   {destroyed_msg}")

                # Defense subtracted once from the per-player total
                # (variant B — restored pre-refactor balance).
                # num_hits is the minimum damage floor (dual-wield = 2, single = 1).
                if num_hits > 0 and not monster.is_dead():
                    total_raw = d  # sequence.total_damage() already computed above
                    defense = monster.get_defense()
                    final_body_dmg = max(num_hits, total_raw - defense)
                    monster.health = max(0, monster.health - final_body_dmg)
                    actual_body_damage += final_body_dmg
                    if monster.health == 0 and not death_msg:
                        death_msg = monster.death if hasattr(monster, 'death') else ""

                if injury_feedback:
                    msg += "\n".join(injury_feedback) + "\n"
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
            key = f"{monster.name}.killed"
            self.monster_statics[key] = 1 if key not in self.monster_statics.keys() else self.monster_statics[key] + 1
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
                key = f"{monster.name}.escaped"
                self.monster_statics[key] = (
                    1 if key not in self.monster_statics.keys() else self.monster_statics[key] + 1
                )
                Dispatcher.add(self.channel, f"{msg}\n{parse(monster.escape, monster)}")
                await self.cancel_combat()

    async def kill_monster(self):
        """Cancels combat and forces monster death."""

        self.game_clock.remove_routine(self.do_combat)
        monster = self.monster
        msg = await self.on_monster_death()
        if len(msg) > 0:
            Dispatcher.add(self.channel, parse(msg, monster))

    async def do_ambience(self):
        """Small chance to display a random ambience message."""

        if not self.enable_ambience:
            _log.debug(f"Removing ambience loop for game on {self.guild.name}.")
            self.game_clock.remove_routine(self.do_ambience)
            return

        game_time = self.game_clock.get_seconds()

        msg = ""

        sunrise, sunset = self.game_clock.get_sunrise_and_sunset()

        if self._last_ambience_tick < sunrise <= game_time:
            msg = "The sky glows softly to the east as night gives way to day."
        elif self._last_ambience_tick < sunset <= game_time:
            msg = "The crimson disc sinks slowly beyond the horizon, and darkness creeps across the land."

        if random.randint(1, 3000) == 3000:
            msg += choice(
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

        if msg:
            Dispatcher.add(self.channel, msg)

        self._last_ambience_tick = game_time

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
            "game_time": self.game_clock.get_seconds(),
        }

        if self.id is not None:
            d["_id"] = self.id

        return d

    # Adds or updates a game object in the database.
    def save(self) -> None:
        """Adds or updates a game object in the database."""

        try:
            DB.update_game(self.guild.id, self.to_dict(), upsert=True)
            if self.id is None:
                game = DB.get_game_by_guild_id(self.guild.id)
                self.id = game["_id"] if game else None
        except Exception as e:
            _log.error(e)

    @classmethod
    async def load(cls, guild_id: int, bot: "Bot") -> Optional["Game"]:
        """Returns a game loaded from the database."""

        if guild_id is None:
            return None

        try:
            g = DB.get_game_by_guild_id(guild_id)
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
            game_time=d["game_time"],
        )

        game.guild = bot.get_guild(d["guild_id"])
        game.channel = bot.get_channel(d["channel_id"])

        if game.guild is None:
            _log.error(f"Failed to load game {d['_id']}: guild {d['guild_id']} not found.")
            return None
        if game.channel is None:
            _log.error(f"Failed to load game {d['_id']}: channel not found for guild {d['guild_id']}.")
            return None

        await game.player_manager.load_players(game.guild)
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
