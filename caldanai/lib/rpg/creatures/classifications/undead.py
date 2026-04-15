"""``Undead`` classification mixin — shared traits and flavor for
creatures brought back from death.

Inherit alongside :class:`MonsterPlugin` (mixin first):

    class Skeleton(Undead, MonsterPlugin):
        ...

Concrete subclasses can still override individual trait values and
HIT_NARRATIONS entries; the mixin's ``setdefault`` and the MRO-walking
narration merge in ``Creature.get_hit_narration`` ensure subclass
choices win.
"""

from caldanai.lib.rpg.helpers.enums import DamageTypes


class Undead:
    """Trait/mixin for creatures brought back from death.

    Applies the standard undead damage-type profile, registers the
    ``"undead"`` flag for downstream identity checks, and provides
    classification-level hit narration for LIGHT and DARK (the two
    damage types whose interaction with undead is universal across
    the classification).

    The trait dict uses ``setdefault`` semantics so a concrete
    monster can tune individual values without losing the rest.
    HIT_NARRATIONS merges via MRO in ``Creature.get_hit_narration``,
    so subclass entries override mixin entries automatically.
    """

    UNDEAD_TRAITS = {
        DamageTypes.LIGHT: 2.0,    # holy radiance — undead universally hate it
        DamageTypes.FIRE:  1.5,    # purification by flame
        DamageTypes.DARK:  0.0,    # dark IS them — immune
        DamageTypes.ICE:   0.5,    # cold does little to the already-cold (compound match)
    }

    HIT_NARRATIONS = {
        DamageTypes.LIGHT: "Holy radiance burns @1d's unliving form.",
        DamageTypes.DARK:  "Shadow flows over @1d like a familiar tide; nothing seems to take hold.",
    }

    def __init__(self, *args, **kwargs):
        # MRO chain: <Concrete>__init__ → Undead.__init__ →
        # MonsterPlugin.__init__ → Creature.__init__. We forward
        # everything up first so ``self.traits`` / ``self.flags``
        # exist before we layer defaults onto them.
        super().__init__(*args, **kwargs)
        for dmg, mult in self.UNDEAD_TRAITS.items():
            # ``setdefault``: don't stomp values a concrete subclass
            # set in its own __init__. Concrete __init__ runs AFTER
            # super(), so subclass-explicit traits will overwrite
            # the defaults below — this just covers the unset cases.
            self.traits.setdefault(dmg, mult)
        self.flags.add("undead")
