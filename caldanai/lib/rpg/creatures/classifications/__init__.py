"""Creature classification mixins.

Each module in this package defines a single classification (Undead,
Construct, Fae, Lupine, etc.) as a mixin class. Concrete monsters
inherit from one or more classifications alongside ``MonsterPlugin``
to declaratively pick up shared damage-trait profiles, narrative
flavor, hooks, and identity flags.

Pattern
=======

A classification mixin should:

- Declare a class-level ``<NAME>_TRAITS`` dict (damage type → multiplier)
  applied via ``setdefault`` in its ``__init__`` so concrete monsters
  can override individual values without losing the rest.
- Optionally declare ``HIT_NARRATIONS`` for damage types that have
  classification-flavored reactions (light vs. undead, magic vs. fae,
  etc.). Concrete monsters can extend or override per type.
- Add a ``self.flags`` entry naming the classification (``"undead"``,
  ``"construct"``, etc.) for downstream hooks and identity checks.
- ``__init__`` MUST call ``super().__init__(*args, **kwargs)`` first
  so the rest of the MRO chain (``MonsterPlugin`` → ``Creature``)
  initializes the creature before the mixin layers its defaults.

Usage:
    class Skeleton(Undead, MonsterPlugin):
        def __init__(self):
            super().__init__(name="skeleton", ...)
            # skeleton-specific overrides happen AFTER super(),
            # so they win over Undead's setdefault defaults.
            self.traits[DamageTypes.BLUDGEONING] = 2.0
"""

from caldanai.lib.rpg.creatures.classifications.undead import Undead

__all__ = ["Undead"]
