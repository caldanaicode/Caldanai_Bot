import asyncio
from datetime import datetime
from typing import Dict, Optional, Union

from discord import Forbidden, Guild, HTTPException, Role, TextChannel, Member, User
from discord.errors import NotFound
from discord.ext.commands import Context

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.db import DB
from caldanai.lib.rpg import Player, Roles
from caldanai.lib.rpg.helpers.parser import parse


_log = get_logger(__name__)


class PlayerManager:
    def __init__(self, channel: Optional[TextChannel] = None):
        self.players: Dict[int, Player] = {}
        self.roles: Dict[Roles, Optional[Role]] = {}
        # Dispatch target for player-scoped narration (regen recovery
        # lines, etc.). Game stamps this at construction and re-stamps
        # it on the load path (``from_dict``) after the channel is
        # resolved from the bot cache. Routines that fire before the
        # channel is bound silently skip dispatch.
        self.channel: Optional[TextChannel] = channel

    async def load_players(self, guild: Guild, channel_id: int = None):
        """Load this game's players into memory.

        Game-scoped (compound ``guild_id`` + ``channel_id`` query)
        as of 2026-05-02 to fix cross-game state bleed: a guild
        running multiple games (e.g. Vael-facing test channel +
        OOC engineering channel) used to load EVERY guild player
        into EACH game's ``PlayerManager`` because the query was
        guild-only. New ``$join`` attempts in the second game
        reported "already a player," ``$skills`` showed the wrong
        game's skills, and any subsequent ``is_dirty`` write would
        have persisted the second channel's id over the first —
        irrecoverably swapping the player to the wrong game.

        ``channel_id`` is required for proper scoping. When None
        (legacy callers that haven't been updated), falls back to
        the old guild-only query for backward compat with pre-
        scoping setups, but logs a warning — every active call
        site should pass ``channel_id``.
        """
        if not guild:
            _log.error("No guild supplied to PlayerManager.load_players()")
            return

        roles = guild.roles or await guild.fetch_roles()
        for r in Roles:
            matches = list(filter(lambda _r: _r.name == r.value, roles))
            self.roles[r] = matches[0] if len(matches) > 0 else None

        try:
            if channel_id is None:
                _log.warning(
                    "PlayerManager.load_players() called without "
                    "channel_id — falling back to guild-only query. "
                    "This pulls every player in the guild and is "
                    "incompatible with multi-game guilds."
                )
                players = list(DB.find_players_by_guild_id(guild.id))
            else:
                players = list(
                    DB.find_players_by_game(guild.id, channel_id)
                )
        except Exception as e:
            _log.error(e)
            return

        # Warm the member cache in a single WebSocket round-trip rather
        # than paying one REST ``fetch_member`` per missing entry. The
        # members intent is enabled (see ``Bot.__init__``), so ``chunk``
        # is the cheapest way to populate every member at once.
        #
        # Two guardrails:
        # 1. Skip entirely when ``guild.chunked`` is True — discord.py
        #    auto-chunks at startup with the members intent enabled, so
        #    by the time ``on_ready`` fires the cache is typically
        #    already populated. Calling ``chunk()`` on a chunked guild
        #    returns immediately in principle, but issuing a second
        #    chunk request while the auto-chunk is still in-flight can
        #    deadlock: the second await waits for gateway state that
        #    can't advance until ``on_ready`` processing finishes,
        #    which can't finish until this await returns.
        # 2. Wrap the call in ``asyncio.wait_for`` so a stuck chunk
        #    drops through to the per-player ``fetch_member`` fallback
        #    below instead of hanging the bot's startup.
        if players and not guild.chunked:
            try:
                await asyncio.wait_for(guild.chunk(), timeout=10)
            except asyncio.TimeoutError:
                _log.warning(f"guild.chunk() timed out for {guild.id}; falling back to per-player fetch.")
            except Exception as e:
                _log.warning(f"guild.chunk() failed for {guild.id}; falling back to per-player fetch. Error: {e}")

        for p in players:
            uid = p["user_id"]
            player = Player.from_dict(p)
            # Bind the player to this game's channel. For legacy docs
            # that pre-date game-scoped players, this is the one-time
            # adoption that makes subsequent saves write channel_id.
            if channel_id is not None:
                player.channel_id = channel_id
            try:
                member = guild.get_member(uid)
                if member is None:
                    # Post-chunk miss means the user isn't in the guild
                    # any more. Fall back to fetch_member so a failed /
                    # skipped chunk still gets the defensive NotFound
                    # path that cleans up ex-members below.
                    member = await guild.fetch_member(uid)
                player.member = member
                player.name = player.member.display_name
                self.players[uid] = player

            except NotFound as e:
                if e.code == 10007:
                    await self.remove_player(uid, guild.id, channel_id)
                    _log.warning(f"Removed player {uid} from game on {guild.id}. Unknown member on server.")

            except Exception as e:
                _log.error(f"Unable to load user id {uid}. Error: {e}")

    def maybe_update_member_name(self, member) -> bool:
        """Sync the in-game player name when a Discord member's
        ``display_name`` changes (nickname or global name). Called
        from the ``on_member_update`` cog listener for every game on
        the affected guild. Returns ``True`` if an update happened.

        Until this hook landed, ``player.name`` was set once at
        ``add_player`` / ``load_players`` time and never refreshed
        — so narration kept using the original name until the next
        bot restart rehydrated from Mongo.
        """
        player = self.players.get(member.id)
        if player is None:
            return False
        if player.name == member.display_name:
            return False
        player.name = member.display_name
        player.member = member
        player.is_dirty = True
        return True

    async def set_player_active(self, player: Player):
        """Updates player's last_active time and changes roles if needed."""
        player.last_active = datetime.now()
        player.is_dirty = True
        if (
            Roles.INACTIVE in self.roles.keys()
            and self.roles[Roles.INACTIVE]
            and self.roles[Roles.INACTIVE] in player.member.roles
        ):
            await player.member.remove_roles(self.roles[Roles.INACTIVE], reason="Activity in game.")

        if (
            Roles.ACTIVE in self.roles.keys()
            and self.roles[Roles.ACTIVE]
            and self.roles[Roles.ACTIVE] not in player.member.roles
        ):
            await player.member.add_roles(self.roles[Roles.ACTIVE], reason="Activity in game.")

    async def set_player_inactive(self, player: Player):
        """Sets a player's role to inactive."""
        reason = "No activity in game for at least 24 hours."
        if (
            Roles.ACTIVE in self.roles.keys()
            and self.roles[Roles.ACTIVE]
            and self.roles[Roles.ACTIVE] in player.member.roles
        ):
            await player.member.remove_roles(self.roles[Roles.ACTIVE], reason=reason)

        if (
            Roles.INACTIVE in self.roles.keys()
            and self.roles[Roles.INACTIVE]
            and self.roles[Roles.INACTIVE] not in player.member.roles
        ):
            await player.member.add_roles(self.roles[Roles.INACTIVE], reason=reason)

    async def update_inactive_roles(self):
        now = datetime.now()
        for player in self.players.values():
            if player.last_active is None or (now - player.last_active).days > 0:
                await self.set_player_inactive(player)

    async def set_player_combatant(self, player: Player):
        """Sets a player's role as a combatant."""
        reason = "Participating in combat."
        if not (
            Roles.COMBAT_MAIN in self.roles.keys()
            and self.roles[Roles.COMBAT_MAIN]
            and self.roles[Roles.COMBAT_MAIN] not in player.member.roles
        ):
            return

        try:
            await player.member.add_roles(self.roles[Roles.COMBAT_MAIN], reason=reason)
            _log.debug(f"Combat role added for {player.name}")
        except (Forbidden, HTTPException):
            _log.warning(f"Addition of combat role failed for {player.name}", exc_info=1)

    async def clear_player_combatant(self, player: Player, reason: str):
        """Removes a player's combat role unconditionally.

        Does NOT gate on ``player.member.roles`` — the cached role
        list can drift from server-side state after reconnects, so
        trusting it would silently skip removals. Discord is
        idempotent about removing a role the member doesn't have.
        """
        if not (
            Roles.COMBAT_MAIN in self.roles.keys()
            and self.roles[Roles.COMBAT_MAIN]
        ):
            return

        try:
            await player.member.remove_roles(self.roles[Roles.COMBAT_MAIN], reason=reason)
            _log.debug(f"Combat role removed for {player.name}")
        except (Forbidden, HTTPException):
            _log.warning(f"Removal of combat role failed for {player.name}", exc_info=1)

    async def clear_combat_roles(self, participants):
        """Remove the combat role from every player who participated.

        ``participants`` is the authoritative list of players who
        received the role (``Game.looters``). Does NOT filter on
        the cached ``member.roles`` — the cache drifts after
        reconnects. Discord is idempotent about removing a role
        the member doesn't have.
        """
        if not self.roles.get(Roles.COMBAT_MAIN):
            return

        reason = "Combat terminated."
        await asyncio.gather(*[
            self.clear_player_combatant(p, reason)
            for p in participants
        ])

    async def get_player(self, ctx: Context) -> Union[Player, None]:
        """
        Returns a Player associated with a context, or None if the Player does not exist.
        """

        if isinstance(ctx, Context) and ctx.author.id in self.players:
            return self.players[ctx.author.id]

        elif isinstance(ctx, (Member, User)) and ctx.id in self.players.keys():
            return self.players[ctx.id]

        return None

    async def add_player(self, ctx: Context) -> bool:
        joined = datetime.now()
        if ctx.author.id not in self.players and (
            player := Player(gid=ctx.guild.id, cid=ctx.channel.id, uid=ctx.author.id, joined=joined, last_active=joined)
        ):
            from caldanai.lib.rpg.helpers.utils import RpgUtilities

            player.member = ctx.author
            player.name = ctx.author.display_name
            # Fresh-creation path only: roll any class-level
            # ``SPAWN_LOADOUT`` into placements. Default
            # ``Player.SPAWN_LOADOUT = {}`` makes this a no-op
            # today; pinning the call now locks the contract for
            # future starter-kit work without re-rolling DB-
            # hydrated returners into fresh gear.
            player._apply_loadout()
            player.is_dirty = True
            # Register in the live players dict immediately.
            # Without this, the Player only shows up after the next
            # bot restart triggers ``load_players`` to rehydrate from
            # Mongo — meaning a fresh joiner can't invoke a single
            # command until the bot reboots. ``new_players`` is a
            # separate deferred-persistence set used by save_all_now
            # to backfill ``_id`` after the first Mongo insert; it
            # is NOT a substitute for the live registry.
            self.players[ctx.author.id] = player
            RpgUtilities.new_players.add(player)
            if Roles.ALL in self.roles.keys() and Roles.ACTIVE in self.roles.keys():
                await player.member.add_roles(
                    self.roles[Roles.ALL], self.roles[Roles.ACTIVE], reason="Player joined game."
                )
            return True
        return False

    async def remove_player(self, user_id: int, guild_id: int, channel_id: int = None):
        if user_id in self.players and (player := self.players[user_id]):
            if (
                player.member
                and self.roles.get(Roles.ALL)
                and self.roles.get(Roles.ACTIVE)
                and self.roles.get(Roles.INACTIVE)
            ):
                to_remove = [
                    self.roles[Roles.ALL],
                    self.roles[Roles.ACTIVE],
                    self.roles[Roles.INACTIVE],
                ]
                if self.roles.get(Roles.COMBAT_MAIN):
                    to_remove.append(self.roles[Roles.COMBAT_MAIN])
                await player.member.remove_roles(*to_remove, reason="Player left game.")
            del self.players[user_id]

        DB.delete_player(guild_id, channel_id, user_id)

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

        Scheduled by ``Game`` as a recurring clock routine. The method
        lives on ``PlayerManager`` because its only state dependency
        is ``self.players``; the dispatch target (``self.channel``) is
        stamped by ``Game`` at construction so the routine stays free
        of a back-reference to the owning game.
        """
        msg = ""
        for player in self.players.values():
            max_health = player.get_health_max()
            body_needs = player.health < max_health

            # Snapshot is_dead BEFORE the heal applies so a regen
            # tick that lifts the player off death (body 0 → positive
            # OR critical part destroyed → restored) can fire the
            # resurrection narration. ``apply_damage``'s tail check
            # is HP-only and won't catch the cascade-revive case
            # (e.g. dead-by-cascade with body > 0). 2026-05-01:
            # surfaced when Caels was-dead transitioned to alive
            # via regen with no "gasps raggedly" beat — same shape
            # as the pray cascade-revive narration fix.
            was_dead = player.is_dead()
            body_before = player.health

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
                    template = injured_part.get_recovery_string(dead=player.is_dead())
                    if template:
                        # Parse through the @ system so pronouns /
                        # names come out naturally (e.g. "Caels winces
                        # as feeling returns to her left arm.").
                        line = parse(template, player)
                        msg += f"\n{line[0].upper()}{line[1:]}"

            # Cascade-revive narration: regen tick brought the
            # player back from is_dead. Emits BEFORE the recovery
            # line in narrative order so readers see "X gasps as
            # life returns" then the per-part transition that
            # enabled it. ``apply_damage``'s HP-only tail already
            # narrates the body-HP revive case (body crossed 0),
            # so we only fire here for cascade-only revives where
            # body HP didn't transition through 0 — otherwise the
            # gasp narrates twice.
            body_hp_revived = body_before <= 0 < player.health
            if was_dead and not player.is_dead() and not body_hp_revived:
                mention = (
                    f"<@!{player.member.id}>"
                    if getattr(player, "member", None) is not None
                    else player.name
                )
                revive_line = parse(
                    f"{mention} suddenly gasps raggedly as life returns to @1o!",
                    player,
                )
                msg = f"\n{revive_line}{msg}"

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

        if msg and self.channel is not None:
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
