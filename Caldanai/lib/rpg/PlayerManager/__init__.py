from datetime import datetime
from typing import Dict, Optional, Union

from discord import Guild, Role, Member, User
from discord.errors import NotFound
from discord.ext.commands import Context

from Caldanai.Logger import stdout
from Caldanai.db import MongoDB
from Caldanai.lib.rpg import Player, Roles


class PlayerManager:
	def __init__(self):
		self.players: Dict[int, Player] = {}
		self.roles: Dict[Roles, Optional[Role]] = {}

	async def load_players(self, guild: Guild):
		if not guild:
			stdout("No guild supplied to PlayerManager.load_players()")
			return

		roles = guild.roles or await guild.fetch_roles()
		for r in Roles:
			matches = list(filter(lambda _r: _r.name == r.value, roles))
			self.roles[r] = matches[0] if len(matches) > 0 else None

		for p in MongoDB.players.find({'guild_id': guild.id}):
			uid = p['user_id']
			player = Player.from_dict(p)
			try:
				player.member = guild.get_member(uid) or await guild.fetch_member(uid)
				player.name = player.member.display_name
				self.players[uid] = player

			except NotFound as e:
				if e.code == 10007:
					await self.remove_player(uid, guild.id)
					stdout(f"Removed player {uid} from game on {guild.id}. Unknown member on server.")

			except Exception as e:
				stdout(f"Unable to load user id {uid}. Error: {e}")

	async def set_player_active(self, player: Player):
		"""Updates player's last_active time and changes roles if needed."""
		player.last_active = datetime.now()
		player.is_dirty = True
		if Roles.INACTIVE in self.roles.keys() \
					and self.roles[Roles.INACTIVE] \
					and self.roles[Roles.INACTIVE] in player.member.roles:
			await player.member.remove_roles(self.roles[Roles.INACTIVE], reason='Activity in game.')

		if Roles.ACTIVE in self.roles.keys() \
					and self.roles[Roles.ACTIVE] \
					and self.roles[Roles.ACTIVE] not in player.member.roles:
			await player.member.add_roles(self.roles[Roles.ACTIVE], reason='Activity in game.')

	async def set_player_inactive(self, player: Player):
		"""Sets a player's role to inactive."""
		reason = 'No activity in game for at least 24 hours.'
		if Roles.ACTIVE in self.roles.keys() \
					and self.roles[Roles.ACTIVE] \
					and self.roles[Roles.ACTIVE] in player.member.roles:
			await player.member.remove_roles(
				self.roles[Roles.ACTIVE],
				reason=reason
			)

		if Roles.INACTIVE in self.roles.keys() \
					and self.roles[Roles.INACTIVE] \
					and self.roles[Roles.INACTIVE] not in player.member.roles:
			await player.member.add_roles(
				self.roles[Roles.INACTIVE],
				reason=reason
			)

	async def update_inactive_roles(self):
		now = datetime.now()
		for player in self.players.values():
			if player.last_active is None or (now - player.last_active).days > 0:
				await self.set_player_inactive(player)

	async def get_player(self, ctx) -> Union[Player, None]:
		"""
		Returns a Player associated with a context, or None if the Player does not exist.
		"""

		if isinstance(ctx, Context) and ctx.author.id in self.players:
			return self.players[ctx.author.id]

		elif isinstance(ctx, (Member, User)) and ctx.id in self.players.keys():
			return self.players[ctx.id]

		return None

	async def add_player(self, ctx) -> bool:
		joined = datetime.now()
		if ctx.author.id not in self.players \
					and (player := Player(gid=ctx.guild.id, uid=ctx.author.id, joined=joined, last_active=joined)):
			player.member = ctx.author
			player.name = ctx.author.display_name
			player.is_dirty = True
			if Roles.ALL in self.roles.keys() and Roles.ACTIVE in self.roles.keys():
				await player.member.add_roles(
					self.roles[Roles.ALL],
					self.roles[Roles.ACTIVE],
					reason="Player joined game."
				)
			return True
		return False

	async def remove_player(self, user_id: int, guild_id: int):
		if user_id in self.players and (player := self.players[user_id]):
			if player.member \
					and Roles.ALL in self.roles.keys() \
					and Roles.ACTIVE in self.roles.keys() \
					and Roles.INACTIVE in self.roles.keys():
				await player.member.remove_roles(
					[self.roles[Roles.ALL], self.roles[Roles.ACTIVE], self.roles[Roles.INACTIVE]],
					'Player left game.'
				)
				del self.players[user_id]

		MongoDB.players.delete_one({'guild_id': guild_id, 'user_id': user_id})