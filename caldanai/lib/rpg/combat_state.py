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

    __slots__ = ("monster", "monsters", "combatants", "combat_targets", "looters", "loot")

    def __init__(self) -> None:
        self.monster: Optional["MonsterPlugin"] = None
        self.monsters: List[str] = []
        self.combatants: List["Player"] = []
        self.combat_targets: Dict[int, Optional[List[str]]] = {}
        self.looters: List["Player"] = []
        self.loot: Dict[int, List[Union["Item", "Weapon"]]] = {}

    async def end_combat(
        self,
        player_manager: "PlayerManager",
        game_clock: "GameClock",
        do_combat_routine,
    ) -> None:
        """Single source of truth for combat teardown.

        Clears combat state (monster, combatants, targets, looters)
        and unconditionally removes combat roles from everyone who
        participated (tracked via ``self.looters`` — the authoritative
        list of players who received the combat role). Does NOT touch
        ``self.loot`` — callers manage the loot lifecycle (generate,
        timer, or clear) before calling this.

        Also removes the periodic ``do_combat`` routine from the game
        clock so no further combat ticks fire once the encounter
        ends.

        Does NOT start the spawn timer — callers follow up with
        ``Game.set_spawn_timer`` when appropriate.
        """
        self.monster = None
        self.combatants.clear()
        self.combat_targets.clear()
        game_clock.remove_routine(do_combat_routine)
        await player_manager.clear_combat_roles(self.looters)
        self.looters.clear()
