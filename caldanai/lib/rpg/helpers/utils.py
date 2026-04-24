import smtplib
import sys
import textwrap

from collections import Counter
from datetime import datetime
from email.message import EmailMessage
from random import choice
import traceback
from typing import List, Tuple, Union

from discord import Forbidden, HTTPException, Member, User, File
from discord.ext import tasks

from caldanai.lib.bot import Bot
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.db import DB
from caldanai.lib.rpg import Game, Area, Roles


_log = get_logger(__name__)

# Cached auth credentials so alerts can be sent even when the DB is unreachable.
_cached_auth = None


def cache_auth():
    """Fetches and caches alert credentials from the database. Call once at startup."""
    global _cached_auth
    try:
        auth_rec = DB.get_auth()
        if auth_rec:
            _cached_auth = {
                "DEV_EMAIL": auth_rec["DEV_EMAIL"],
                "SMTP_USER": auth_rec["SMTP_USER"],
                "SMTP_PASSWORD": auth_rec["SMTP_PASSWORD"],
                "SMS_EMAIL": auth_rec["SMS_EMAIL"],
            }
            _log.debug("Alert credentials cached.")
        else:
            _log.error("cache_auth: no auth record found in database.")
    except Exception:
        _log.error("cache_auth: failed to cache alert credentials.", exc_info=True)


def generate_report(
    author_id,
    author_display_name,
    message: str,
    player_name=None,
    guild_id=None,
    channel_id=None,
):
    # Try live DB first, fall back to cached credentials.
    auth_rec = None
    try:
        auth_rec = DB.get_auth()
    except Exception:
        pass

    if not auth_rec:
        auth_rec = _cached_auth

    if not auth_rec:
        _log.error("Reporting error: unable to retrieve authentication information from database or cache.")
        return False

    msg = EmailMessage()
    msg["Subject"] = "Problem report from Caldanai Bot."
    msg["From"] = auth_rec["DEV_EMAIL"]
    msg["To"] = auth_rec["DEV_EMAIL"]
    msg.set_content(
        textwrap.dedent(
            f"""\
            Timestamp: {datetime.now().isoformat()}
            Author: {author_id} ({author_display_name} / {player_name})
            Guild ID: {guild_id}
            Channel ID: {channel_id}
            Details:
            {message}
            """
        )
    )

    # Send full email
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(auth_rec["SMTP_USER"], auth_rec["SMTP_PASSWORD"])
        s.send_message(msg)

        # Send text alert
        msg.set_content("A new alert has been received. Please check your email.")
        del msg["To"]
        msg["To"] = auth_rec["SMS_EMAIL"]
        s.send_message(msg)
        s.quit()
        return True


class RpgUtilities:
    bot: Bot = None
    is_initialized: bool = False
    new_players = set()

    @staticmethod
    def dead_invoker_guard(channel, player, flavor: Union[str, List[str]]) -> bool:
        """Short-circuit guard for commands that don't apply when the
        invoker is dead.

        When ``player.is_dead()`` is ``True``, emits one flavor line
        to ``channel`` and returns ``True``; the calling handler
        should immediately ``return``. Otherwise returns ``False``
        and the handler proceeds with its real body.

        ``flavor`` is either a parse-template string (single fixed
        line — the common case for inventory / attack / hug) or a
        list of them (random pick — used by the goofy fun-commands
        that want variety). The parse engine is applied with the
        invoker as ``@1`` so templates can use ``@1``/``@1np``/etc.
        for natural noun/pronoun forms. Handlers that want to
        reference both the invoker and a target should handle death
        checks inline rather than via this helper — it's
        deliberately one-actor by design so the call-site stays a
        one-liner.

        Usage::

            if RpgUtilities.dead_invoker_guard(
                game.channel, player, "A ghostly moan escapes the corpse of @1."
            ):
                return

        Does NOT cover the inverse case (commands where dead is a
        required or meaningful state, e.g. ``$haunt`` and ``$pray``)
        — those branch on death deliberately and don't fit the
        guard shape.
        """
        if not player.is_dead():
            return False
        line = choice(flavor) if isinstance(flavor, list) else flavor
        Dispatcher.add(channel, parse(line, player))
        return True

    # Checks the given context to see if a game exists for it.
    @staticmethod
    async def check_game_exists(ctx) -> bool:
        if ctx.guild is None:
            Dispatcher.add(ctx, f"I'm afraid I can't do that from here, {ctx.author.display_name}.")
        elif ctx.channel.id not in RpgUtilities.bot.games.keys():
            Dispatcher.add(ctx, f"I'm afraid there is no game in this channel, {ctx.author.display_name}")
        else:
            return True
        return False

    @staticmethod
    async def create_roles(game: Game):
        try:
            pmgr = game.player_manager
            for role in Roles:
                if role not in pmgr.roles.keys() or (role in pmgr.roles.keys() and not pmgr.roles[role]):
                    pmgr.roles[role] = await game.guild.create_role(
                        name=f"{role.value}",
                        mentionable=True,
                        reason="Created by Caldanai Bot for directing mentions to only active players.",
                    )

            for player in pmgr.players.values():
                if pmgr.roles[Roles.ALL] not in player.member.roles:
                    await player.member.add_roles(
                        pmgr.roles[Roles.ALL], reason="Is a player in the Caldanai Bot's game."
                    )

        except Forbidden:
            _log.error(f"No permission to create roles in guild '{game.guild.name}'.")

        except HTTPException as e:
            _log.error(f"HTTPException while trying to add roles: {e}")
            raise

    @staticmethod
    async def delete_roles(game: Game):
        try:
            for key, role in game.player_manager.roles.items():
                if role:
                    await role.delete(reason="Caldanai Bot's game removed from server")
                    game.player_manager.roles[key] = None

        except Forbidden:
            _log.error(f"No permission to remove roles in guild '{game.guild.name}'.")

        except HTTPException as e:
            _log.error(f"HTTPException while trying to remove roles: {e}")
            raise

    # Adds a game to the bot's list of games
    @staticmethod
    async def add_game(
        game: dict = None,
        gid: int = None,
        chid: int = None,
        timer: bool = True,
        spawn_range: List[int] = [600, 3600],
        spawn_duration: int = 10,
        loot_duration: int = 5,
    ):
        if gid is not None and chid is not None:
            guild = RpgUtilities.bot.get_guild(gid) or await RpgUtilities.bot.fetch_guild(gid)
            channel = RpgUtilities.bot.get_channel(chid) or await RpgUtilities.bot.fetch_channel(chid)

            try:
                DB.get_server_by_guild_id(gid)["prefix"]
            except Exception as e:
                _log.error(f"Error in utils.py --> add_game(): {e}")
                return

            if game is None:
                game = Game(
                    RpgUtilities.bot,
                    None,
                    guild,
                    channel,
                    timer,
                    tuple(spawn_range),
                    spawn_duration,
                    loot_duration,
                )
                await game.player_manager.load_players(guild, channel.id)
                await RpgUtilities.create_roles(game)
                game.save()

        else:
            game = await Game.from_dict(game, RpgUtilities.bot)

        room0 = Area.from_plugin("0")
        game.room0 = room0
        # Channel routing is populated inside ``Game.__init__`` /
        # ``Game.from_dict`` via ``register_channel``; ``bot.games`` is
        # a read-only live view over that registry, so there's no
        # separate per-bot map to maintain here.
        _log.info(f"Game added for guild: {game.guild.name} ({game.guild.id})")
        startup_msg = "Caldanai Bot has just started!"
        if getattr(game, "weather", None) is not None:
            # Surface current weather at startup so players don't have
            # to ``$weather`` to know what they woke up to.
            startup_msg += f"\n\n{game.weather.describe()}"
        Dispatcher.add(game.channel, startup_msg)

    # Gets a list of games to which a user belongs.
    @staticmethod
    def get_games_for_user(uid: int) -> List[Game]:
        """
        Returns a list of Games for the given discord user id.
        """

        games = []
        if uid is None:
            return games
        try:
            players = DB.find_players_by_user_id(uid)
            for player in players:
                # Player docs gain ``channel_id`` on first save after
                # migration. Legacy docs without it fall back to
                # guild_id for the lookup — this may miss in a
                # channel-keyed dict, but resolves after first save.
                key = player.get("channel_id") or player.get("guild_id")
                if key in RpgUtilities.bot.games:
                    games.append(RpgUtilities.bot.games[key])

            return games

        except Exception as e:
            _log.error(f"Error in utils.py --> get_games_for_user(): {e}")
            return []

    # Get the game associated with a context, if it exists.
    @staticmethod
    async def get_game(ctx, game_idx: int = None) -> Union[Game, None]:
        """
        Returns a Game associated with a context, or by index, if it
        exists. Otherwise returns None.

        ``ctx`` is most often a ``Context`` (command invocation), but
        is also sometimes a ``Member`` or ``User`` when a caller
        passes a mention straight through (e.g. ``$smite @player``
        iterating ``ctx.message.mentions``). Members have ``.guild``
        but no ``.channel``, so we detect the shape via ``hasattr``
        and fall back to the user-lookup path — matching the DM
        case where there's no channel context either.
        """

        game: Union[Game, None] = None
        games: List[Game] = []

        # Member / User objects have no .channel — route via user
        # lookup rather than the channel-keyed map. DM context
        # (``ctx.guild is None``) uses the same path.
        ctx_channel = getattr(ctx, "channel", None)
        if ctx.guild is None or ctx_channel is None:
            # ``Context`` exposes the invoker as ``ctx.author``; a
            # bare ``Member`` / ``User`` IS the invoker and uses
            # ``.id`` directly.
            uid = ctx.author.id if hasattr(ctx, "author") else ctx.id
            games = RpgUtilities.get_games_for_user(uid)
        else:
            game = RpgUtilities.bot.games.get(ctx_channel.id)

        if len(games) == 0 and game is None:
            Dispatcher.add(ctx, f"You are not a member of any games at this time.")

        if game is None:
            if len(games) > 1 and game_idx is None:
                Dispatcher.add(
                    ctx,
                    f"You are playing more than one game and did not supply the game's index."
                    f" Check `{ctx.prefix}games` to get the index of the game from which you wish to"
                    f" view your profile, or try again from the game's channel.",
                )
                return None
            elif len(games) > 1 and len(games) > game_idx >= 0:
                return games[game_idx]
            elif len(games) == 1:
                return games[0]
            else:
                Dispatcher.add(ctx, f"The game is a lie! (No seriously... there seems to be no game available.)")

        return game

    @staticmethod
    async def get_player(ctx, game: Game = None, notify: bool = True) -> Union[Player, None]:
        """
        Returns a Player associated with a context, or None if the Player does not exist.
        """

        if game is None or not isinstance(game, Game):
            if (game := await RpgUtilities.get_game(ctx)) is None:
                return None

        if player := await game.player_manager.get_player(ctx):
            return player

        if notify:
            if isinstance(ctx, (Member, User)) and ctx.bot:
                file = File(f"./site/static/images/hal9000.gif", filename="hal9000.gif")
                Dispatcher.add(game.channel, file=file)
                return None

            Dispatcher.add(
                game.channel,
                f"Why, {ctx.author.display_name if ctx.author else ctx.display_name}! You are not even playing the "
                f"game! Try `{ctx.prefix}game join`",
            )
        return None

    # Returns a tuple containing (game, player) if both exist.
    @staticmethod
    async def get_game_and_player(ctx, game_idx: int = None, notify: bool = True) -> Tuple[Game, Player]:
        """
        Returns a tuple containing a Game and Player if they exist, or None for one or both upon failure.
        """

        game: Game = await RpgUtilities.get_game(ctx, game_idx)
        if game is None:
            return None, None

        player: Player = await RpgUtilities.get_player(ctx, game, notify)
        return game, player

    # Pick the right reply target for a cog command: the game's bound
    # channel when invoked from a guild, or the invoking context
    # itself when invoked from a DM (so replies go back to the user).
    # Cogs used to inline this ternary at every call site; centralize
    # it here so behavior stays consistent.
    @staticmethod
    def resolve_reply_channel(ctx, game: Game):
        """Return ``game.channel`` for guild invocations, else ``ctx``.

        Mirrors the previous cog-level idiom
        ``game.channel if ctx.guild is not None else ctx`` exactly —
        no behavior change, just deduplication.
        """
        return game.channel if getattr(ctx, "guild", None) is not None else ctx

    @staticmethod
    def resolve_items_or_notify(
        channel,
        player,
        raw_queries: List[str],
        mode: str,
    ) -> "List[Tuple[Item, Optional['EquipmentSlots']]]":
        """Resolve a list of raw item queries into
        ``(item, placement_override)`` pairs, dispatching any
        needed user-facing messages (no-match, ambiguity, bad
        slot hint) along the way.

        Query grammar::

            <raw-query> ::= <item-query>[@<placement-hint>]
            <placement-hint> ::= l|left|r|right|_|<part.key>|<key>

        For each query:

        1. Split on ``@`` to separate the item portion from the
           optional placement hint.
        2. Run the item portion through
           :meth:`Player.resolve_item_query` in the supplied
           ``mode``.
        3. Resolve the placement hint (if any) to an
           :class:`EquipmentSlots` mask via the short-form
           vocabulary (``l`` / ``left`` → ``LEFT_SIDE`` mask,
           ``r`` / ``right`` → ``RIGHT_SIDE``) or the
           ``(part, key)`` routing table (``head.worn`` →
           ``HEAD``, ``outer`` → ``CAPE``, etc.).
        4. Append ``(item, placement)`` pairs to the result for
           successful resolutions. Skip silently (after
           dispatching a user message) when a query can't be
           resolved or is ambiguous.

        Returns the list of ``(item, placement)`` pairs. Empty
        list means either nothing resolved or every query
        produced a user-facing message — caller should short-
        circuit either way.

        Single-select modes (``equip`` / ``stow`` / ``item``)
        produce at most one pair per query; ``sell`` produces
        zero-or-more per query (the resolver returns every
        matching unequipped item).
        """
        from caldanai.lib.rpg.creatures.equipment_routing import SLOT_TO_PART_KEY, SLOT_PAIR
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots

        results: List[Tuple[Item, Optional[EquipmentSlots]]] = []

        for raw in raw_queries:
            if not isinstance(raw, str):
                continue
            stripped = raw.strip()
            if not stripped:
                continue

            # Split on '@' — before is the item query, after is
            # the optional placement hint.
            if "@" in stripped:
                item_q, _, hint_raw = stripped.partition("@")
                item_q = item_q.strip()
                hint_raw = hint_raw.strip()
            else:
                item_q, hint_raw = stripped, ""

            resolution = player.resolve_item_query(item_q, mode)

            if not resolution.items:
                if resolution.ambiguity_candidates:
                    cand_list = ", ".join(
                        f"`{c}`" for c in resolution.ambiguity_candidates
                    )
                    Dispatcher.add(
                        channel,
                        f"I see multiple matches for `{item_q}` — "
                        f"did you mean one of: {cand_list}?",
                    )
                else:
                    Dispatcher.add(
                        channel,
                        f"You don't seem to have anything matching `{item_q}`.",
                    )
                continue

            # Resolve the placement hint, if any.
            placement: "Optional[EquipmentSlots]" = None
            if hint_raw:
                hint_lower = hint_raw.lower()
                if hint_lower in ("l", "left"):
                    placement = EquipmentSlots.LEFT_SIDE
                elif hint_lower in ("r", "right"):
                    placement = EquipmentSlots.RIGHT_SIDE
                elif hint_lower == "_":
                    # Whole-mask equip (what ``_`` meant historically
                    # in the old $equip slot arg). Leave placement
                    # None so the equip handler treats it as
                    # "auto-route to anything compatible".
                    placement = None
                else:
                    # Try as a (part, key) placement or bare key:
                    # reverse-lookup every SLOT_TO_PART_KEY entry
                    # and every SLOT_PAIR entry to find a slot
                    # mask that matches.
                    tokens = hint_lower.split(".")
                    matched_slot: "Optional[EquipmentSlots]" = None

                    # Full ``part.key`` match.
                    if len(tokens) >= 2:
                        for split in range(len(tokens) - 1, 0, -1):
                            p = ".".join(tokens[:split])
                            k = ".".join(tokens[split:])
                            for slot, (sp, sk) in SLOT_TO_PART_KEY.items():
                                if sp == p and sk == k:
                                    matched_slot = slot
                                    break
                            if matched_slot is not None:
                                break
                            for slot, pair in SLOT_PAIR.items():
                                if any(sp == p and sk == k for (sp, sk) in pair):
                                    matched_slot = slot
                                    break
                            if matched_slot is not None:
                                break

                    # Bare-key match.
                    if matched_slot is None:
                        for slot, (_, k) in SLOT_TO_PART_KEY.items():
                            if k == hint_lower:
                                matched_slot = slot
                                break
                        if matched_slot is None:
                            for slot, pair in SLOT_PAIR.items():
                                if any(k == hint_lower for (_, k) in pair):
                                    matched_slot = slot
                                    break

                    if matched_slot is None:
                        Dispatcher.add(
                            channel,
                            f"I don't know the slot `{hint_raw}`. "
                            f"Try `l`/`left`/`r`/`right`/`_`, or a "
                            f"placement key like `head.worn` or `outer`.",
                        )
                        continue
                    placement = matched_slot

            for item in resolution.items:
                results.append((item, placement))

        return results

    @staticmethod
    async def init(bot: Bot):
        try:
            RpgUtilities.bot = bot
            cache_auth()
            games: List[Game] = list(DB.find_all_games())
            MonsterPlugin.load_plugins()
            for g in games:
                await RpgUtilities.add_game(game=g)
            _log.info("Starting save_game_data loop")
            save_game_data.start()

            if not DB.watchdog.is_running():
                _log.info("Starting watchdog loop")
                DB.watchdog.start()

            RpgUtilities.is_initialized = True

        except Exception as e:
            _log.error(f"Error initializing RpgUtilities: {e}")
            RpgUtilities.is_initialized = False

    # Removes a game from the bot's list of games
    @staticmethod
    async def remove_game(guild_id: int, channel_id: int):
        """Remove the game keyed by ``channel_id`` from memory, the
        DB, and channel routing. ``guild_id`` is still required for
        the DB compound key.

        ``bot.games`` is a read-only view over
        ``Game._channel_routes``, so dropping the channel from that
        registry (via ``unregister_channel``) is what makes the game
        disappear from ``bot.games`` — no separate dict delete.
        ``GameClock.for_channel`` resolves through the same routing
        map, so unregistering the channel also makes the clock
        unfindable — no separate clock-registry teardown."""
        if channel_id in RpgUtilities.bot.games:
            try:
                game = RpgUtilities.bot.games.get(channel_id)
                DB.delete_game(guild_id, channel_id)
                await RpgUtilities.delete_roles(game)

                # Stop per-game daemons + clock tick FIRST so no
                # routines fire against a defunct channel, then
                # unhook from channel routing.
                if game is not None:
                    if getattr(game, "weather", None) is not None:
                        game.weather.stop()
                    if getattr(game, "celestial", None) is not None:
                        game.celestial.stop()
                    if game.game_clock.tick.is_running():
                        game.game_clock.tick.stop()
                    game.unregister_channel(channel_id)

            except Exception as e:
                _log.error(f"Error in utils.py --> remove_game(): {e}")

    @staticmethod
    def update_statics():
        command_totals = {}
        game_totals = {}
        try:
            cmd_copy, RpgUtilities.bot.command_usage = RpgUtilities.bot.command_usage, []
            mon_copy = {}
            for g in RpgUtilities.bot.games.values():
                mon_copy[g], g.monster_statics = g.monster_statics, Counter()

            for entry in cmd_copy:
                DB.update_user_statics(entry)
                key = (entry["guild_id"], entry.get("channel_id"))
                cmd = f'commands.{entry["command"]}.{entry["alias"]}'
                totals = command_totals.setdefault(key, {})
                totals[cmd] = totals.get(cmd, 0) + 1
                game_totals[key] = game_totals.get(key, 0) + 1

            for (guild_id, channel_id), commands in command_totals.items():
                DB.update_statistic(
                    guild_id,
                    {**commands, "total": game_totals.get((guild_id, channel_id), 0)},
                    channel_id=channel_id,
                )

            for g, statics in mon_copy.items():
                for key, count in statics.items():
                    DB.update_statistic(g.guild.id, {f"monsters.{key}": count}, channel_id=g.channel.id)

        except Exception:
            e = sys.exception()
            _log.error(f"Error in utils.py --> update_games() for guild_id {e}")


def save_all_now() -> None:
    """Enqueue a DB write for every game and every dirty player.

    Extracted from the body of :func:`save_game_data` so it can be
    invoked once on shutdown without waiting for the next minute-
    boundary tick. Does not itself write to Mongo — it only
    populates ``DB._queues`` via the usual ``DB.update_*`` helpers.
    A follow-up :meth:`DB.flush_all` drains those queues
    synchronously.

    Safe to call while the :func:`save_game_data` task is still
    running; both paths just enqueue, and the double-buffer handles
    concurrent puts. The shutdown path stops the task first anyway
    to keep the ordering unambiguous.
    """
    try:
        for g in RpgUtilities.bot.games.values():
            DB.update_game(g.guild.id, g.channel.id, g.to_dict())
            for p in g.player_manager.players.values():
                if p.is_dirty:
                    DB.update_player(g.guild.id, g.channel.id, p.user_id, p.to_dict())
                    p.is_dirty = False

        for player in RpgUtilities.new_players.copy():
            if player.id is None:
                p = DB.get_player(player.guild_id, player.channel_id, player.user_id)
                if p:
                    player.id = p["_id"]
                    RpgUtilities.new_players.remove(player)

        RpgUtilities.update_statics()
    except Exception:
        error_info = traceback.format_exc()
        _log.error(f"Error in save_all_now(): {error_info}")


@tasks.loop(minutes=1)
async def save_game_data():
    """Single driver for the DB write pipeline: populate queues
    from dirty state, then drain them to Mongo — both in the same
    tick.

    Pre-collapse (2026-04-21): this loop and ``DB.batch_write``
    each ran independently on 1-minute ticks. Ops put into the
    DoubleBuffer by one loop waited for the other's phase offset
    to come around (0–60s additional latency), so a user action
    could sit for up to 2 minutes end-to-end. Collapsing both
    steps into this single loop caps the window at 1 minute while
    preserving the DoubleBuffer's "swap before drain" semantic —
    writes that land during the bulk_write itself go into the
    new-active queue and get flushed next cycle.
    """
    save_all_now()
    await DB.drain_queues_once()


@save_game_data.error
async def save_loop_error(e):
    error_info = traceback.format_exc()
    _log.error(f"Error in save_game_data loop: {error_info}")
