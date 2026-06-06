"""Combat-scoped state for a :class:`Game`.

Extracted from :class:`caldanai.lib.rpg.Game` to keep combat-runtime
bookkeeping separate from the game's persistent / ambient concerns
(clock, weather, player registry, channel routing). The state here is
transient — none of it is persisted by :meth:`Game.to_dict` — and is
wiped by :meth:`CombatState.end_combat` between spawns.

``Game`` proxies the original attribute names (``monster``,
``monsters``, ``combatants``, ``combat_targets``, ``looters``,
``loot``) through ``@property`` accessors that delegate to its
``combat`` field, so existing callers (cogs, tests, monster hooks) can
keep reading and writing ``game.monster`` / ``game.loot`` /
``game.combatants`` as before — this restructuring is internal.
"""

from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
    from caldanai.lib.rpg.creatures.player import Player
    from caldanai.lib.rpg.inventory.item import Item
    from caldanai.lib.rpg.inventory.equipment.weapons import Weapon
    from caldanai.lib.rpg.player_manager import PlayerManager
    from caldanai.lib.rpg.time import GameClock


class CombatState:
    """Owns the six combat-runtime fields that used to live directly
    on ``Game``.

    Attributes
    ----------
    monster:
        The currently-spawned :class:`MonsterPlugin`, or ``None`` when
        no encounter is live.
    monsters:
        A list of monster plugin names — currently unused at runtime,
        reserved for planned multi-monster spawns (swarms / packs).
    combatants:
        Players who have opted into the active encounter and will
        resolve an attack on the next ``do_combat`` tick.
    combat_targets:
        Per-player explicit body-part targeting set via ``$target`` /
        ``$kill <part>``. Keyed by ``player.user_id``; value is a list
        of canonical part names, or ``None`` to attack randomly.
    looters:
        The authoritative list of players who received the combat role
        during this encounter — used both to grant loot on
        ``on_monster_death`` and to strip the role in ``end_combat``.
    loot:
        Player-scoped loot drops keyed by ``player.user_id``. Lifecycle
        is managed by the caller (``on_monster_death`` generates,
        ``$loot`` / ``loot_expires`` clear); ``end_combat`` never
        touches it.
    """

    __slots__ = (
        "monster", "monsters", "combatants", "combat_targets",
        "looters", "loot", "loot_size_at_start",
    )

    def __init__(self) -> None:
        self.monster: Optional["MonsterPlugin"] = None
        self.monsters: List[str] = []
        self.combatants: List["Player"] = []
        self.combat_targets: Dict[int, Optional[List[str]]] = {}
        self.looters: List["Player"] = []
        self.loot: Dict[int, List[Union["Item", "Weapon"]]] = {}
        # Snapshot of total loot-pile size at combat start, used by
        # ``Game._finalize_combat`` to decide whether to fire the
        # post-combat ``$loot`` prompt. Stale ground-litter from a
        # prior encounter that hasn't expired yet would otherwise
        # trigger a misleading prompt on a sheep walk-off / dragon
        # fly-off; comparing end-size to start-size ensures the
        # prompt only fires when THIS combat actually added loot.
        self.loot_size_at_start: int = 0

    async def end_combat(
        self,
        player_manager: "PlayerManager",
        game_clock: "GameClock",
        do_combat_routine,
    ) -> None:
        """Full combat teardown — convenience wrapper that calls
        :meth:`tear_down_state` and :meth:`release_combat_roles` back
        to back. Use this for paths that DON'T dispatch a post-combat
        announce containing the ``RPG Combatant`` role-mention (error
        paths, admin ``$creature kill``, etc.).

        The normal ``_finalize_combat`` death/flee path splits the
        two halves explicitly so the role-mention in the loot-announce
        still pings everyone — see :meth:`tear_down_state` and
        :meth:`release_combat_roles` for the ordering contract.
        """
        await self.tear_down_state(game_clock, do_combat_routine)
        await self.release_combat_roles(player_manager)

    async def tear_down_state(
        self,
        game_clock: "GameClock",
        do_combat_routine,
    ) -> None:
        """Clear combat STATE only — monster, combatants, targets,
        the recurring ``do_combat`` clock routine, and the loot-size
        snapshot. Deliberately leaves ``looters`` intact and the
        Discord combat-role still attached to every participant so a
        post-combat announce containing the ``<@&combatant>`` mention
        still pings them.

        Pairs with :meth:`release_combat_roles`, which the caller
        invokes (typically via ``game_clock.add_routine`` with a small
        delay) AFTER the announce has been dispatched. Without that
        deferral, the role-mention pings an empty role and the loot
        notice reaches nobody. Bug pattern Caels caught 2026-05-25.
        """
        self.monster = None
        self.combatants.clear()
        self.combat_targets.clear()
        game_clock.remove_routine(do_combat_routine)
        self.loot_size_at_start = 0

    async def release_combat_roles(
        self, player_manager: "PlayerManager",
    ) -> None:
        """Remove the ``RPG Combatant`` Discord role from every
        looter, then clear the looters list. Pairs with
        :meth:`tear_down_state` — call after the post-combat announce
        has been dispatched so the role-mention in the announce still
        resolves against the populated role.

        Idempotent on empty ``looters`` (early-return) so re-entry
        through error paths doesn't double-remove or crash.
        """
        if not self.looters:
            return
        await player_manager.clear_combat_roles(self.looters)
        self.looters.clear()
