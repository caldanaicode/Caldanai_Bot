import asyncio
from datetime import datetime
from typing import Dict, Optional, Union

from discord import Forbidden, Guild, HTTPException, Role, Member, User
from discord.errors import NotFound
from discord.ext.commands import Context

from caldanai.logger import get_logger
from caldanai.db import DB
from caldanai.lib.rpg import Player, Roles


_log = get_logger(__name__)


class PlayerManager:
    def __init__(self):
        self.players: Dict[int, Player] = {}
        self.roles: Dict[Roles, Optional[Role]] = {}

    async def load_players(self, guild: Guild, channel_id: int = None):
        """Load all players for a guild into memory. ``channel_id``
        is stamped onto each loaded player so they know which game
        they belong to. Legacy DB docs missing ``channel_id`` are
        adopted on load and self-migrate on next save."""
        if not guild:
            _log.error("No guild supplied to PlayerManager.load_players()")
            return

        roles = guild.roles or await guild.fetch_roles()
        for r in Roles:
            matches = list(filter(lambda _r: _r.name == r.value, roles))
            self.roles[r] = matches[0] if len(matches) > 0 else None

        try:
            # Guild-scoped query for backward compat — legacy docs
            # lack channel_id, so a compound query would miss them.
            # Players are bound to *this* game at runtime by stamping
            # channel_id below; next save writes it to the doc.
            players = (p for p in DB.find_players_by_guild_id(guild.id))
        except Exception as e:
            _log.error(e)
            return

        for p in players:
            uid = p["user_id"]
            player = Player.from_dict(p)
            # Bind the player to this game's channel. For legacy docs
            # that pre-date game-scoped players, this is the one-time
            # adoption that makes subsequent saves write channel_id.
            if channel_id is not None:
                player.channel_id = channel_id
            try:
                player.member = guild.get_member(uid) or await guild.fetch_member(uid)
                player.name = player.member.display_name
                self.players[uid] = player

            except NotFound as e:
                if e.code == 10007:
                    await self.remove_player(uid, guild.id, channel_id)
                    _log.warning(f"Removed player {uid} from game on {guild.id}. Unknown member on server.")

            except Exception as e:
                _log.error(f"Unable to load user id {uid}. Error: {e}")

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
        """Removes a player's role as a combatant."""
        if not (
            Roles.COMBAT_MAIN in self.roles.keys()
            and self.roles[Roles.COMBAT_MAIN]
            and self.roles[Roles.COMBAT_MAIN] in player.member.roles
        ):
            return

        try:
            await player.member.remove_roles(self.roles[Roles.COMBAT_MAIN], reason=reason)
            _log.debug(f"Combat role removed for {player.name}")
        except (Forbidden, HTTPException):
            _log.warning(f"Removal of combat role failed for {player.name}", exc_info=1)

    async def clear_combat_roles(self):
        """Clears all combatant roles and warns if any stragglers remain."""
        if Roles.COMBAT_MAIN not in self.roles.keys():
            return

        reason = "Combat terminated."
        combatants: list[Player] = [
            p for p in self.players.values() if self.roles[Roles.COMBAT_MAIN] in p.member.roles
        ]

        if not combatants:
            return

        await asyncio.gather(*[self.clear_player_combatant(p, reason) for p in combatants])

        # Sanity check: verify everyone was cleared (accounts for Discord cache lag
        # or a remove_roles call that failed but was silently caught)
        stragglers = [
            p.name for p in self.players.values() if self.roles[Roles.COMBAT_MAIN] in p.member.roles
        ]
        if stragglers:
            _log.warning(
                f"Players still have combat role after cleanup: {', '.join(stragglers)}"
            )

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
            player.is_dirty = True
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
                await player.member.remove_roles(
                    self.roles[Roles.ALL],
                    self.roles[Roles.ACTIVE],
                    self.roles[Roles.INACTIVE],
                    reason="Player left game.",
                )
            del self.players[user_id]

        DB.delete_player(guild_id, channel_id, user_id)
