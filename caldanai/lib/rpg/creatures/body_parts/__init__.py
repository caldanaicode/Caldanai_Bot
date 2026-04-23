"""BodyPartPlugin base class and plugin-discovery machinery.

Mirrors ``Caldanai.lib.rpg.creatures.monsters.MonsterPlugin``:

- Individual body parts are authored as Python plugin files under this
  package (``body_parts/``), one class per file.
- Each concrete plugin subclasses :class:`BodyPartPlugin` and declares
  class-level defaults for ``name``, ``health_max``, ``is_critical``,
  ``traits``, ``exposure``, and ``debuffs``.
- ``BodyPartPlugin.load_plugins()`` delegates to
  :class:`Caldanai.PluginManager` for filesystem discovery, matching the
  ``MonsterPlugin`` idiom exactly.
- A name-keyed registry (``_PLUGIN_REGISTRY``) is populated after load so
  the item 1.5 factory (``BodyPart.make``) can look plugins up by their
  declared ``name``.
"""

from os import sep
from typing import TYPE_CHECKING, Dict, Optional, Type

from caldanai import PluginManager
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.mixins import Equippable
from caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels, Reach, Stat

if TYPE_CHECKING:
    pass


class BodyPartPlugin(BodyPart):
    """Base class for body-part plugins.

    This class is not meant to be instantiated directly as a plugin; it
    exists so concrete part files (``head.py``, ``leg.py``, ...) can
    subclass it and declare their defaults as class-level attributes.

    Subclasses override the class-level fields below. The constructor
    reads those class-level defaults and passes them through to
    :class:`BodyPart`'s ``__init__``, while still allowing per-instance
    overrides via kwargs (e.g. ``LegPlugin(name="leg.left")``).
    """

    BASEPATH: str = sep.join([
        "caldanai",
        "lib",
        "rpg",
        "creatures",
        "body_parts",
    ])

    # --- Class-level defaults; concrete plugins override these. ---------
    name: str = ""
    health_max: int = 1
    is_critical: bool = False
    traits: Dict[DamageTypes, float] = {}
    exposure: Dict[Reach, float] = {}
    debuffs: Dict[InjuryLevels, Dict[Stat, int]] = {}
    # Default combat actions this part contributes to its owner's
    # ``pick_actions`` pool. Each entry is a dict carrying ``cost`` /
    # ``weight`` / ``dice`` / ``dmg_type`` / ``reach`` / ``label`` /
    # ``narrative``. Phase 3 populates this on the active plugins
    # (``HeadPlugin``, ``ArmPlugin``, etc.); Phase 2 keeps it empty
    # so pipeline orchestration is testable without content yet.
    DEFAULT_ACTIONS: Dict[str, Dict] = {}

    # Q.6 bleed-through multiplier: fraction of damage-to-this-part
    # that flows into the creature's body HP via the post-resolve
    # bleed formula in ``MonsterPlugin.attack_random`` /
    # ``Game._run_player_block`` / ``Hydra.attack_random``. Per-class
    # defaults land on the concrete plugins; the base stays at 1.0 so
    # unknown plugins (custom per-monster parts) bleed fully by
    # default rather than silently dropping body damage.
    bleed_rate: float = 1.0

    # Q.6.3 additive defense adjustment applied when this part is the
    # hit target. Formula: ``defense_per_hit = max(0, base_def +
    # defense_bonus)``. **Default is ``SOFT_PART``** so unarmored
    # parts clamp to zero absorption regardless of creature base_def
    # — monster armor is opt-in per-part (tank torso +3, dragon
    # scales +5, etc.). This matches the playtested balance from the
    # "default-0 multiplier" run: unarmored creatures feel unarmored,
    # and base_def only bites on parts that explicitly declare a
    # positive bonus.
    #
    # Additive (int) rather than multiplicative (float) because
    # integer math is exact at small base_def values (no ``int()``-
    # truncation noise) and because "torso absorbs base_def + 3"
    # reads directly without mental arithmetic. Wired in
    # ``Creature.resolve_attack``.

    # Sentinel for parts that always clamp to zero defense regardless
    # of creature base_def (eye, belly on armored creatures, and the
    # default for every part). Named so ``defense_bonus = SOFT_PART``
    # reads at the declaration site rather than a raw ``-999``.
    SOFT_PART = -999

    defense_bonus: int = SOFT_PART

    # Name-keyed registry populated by :meth:`load_plugins`. Mirrors
    # ``PluginManager.LOADED_PLUGINS`` but keyed by the plugin's declared
    # ``name`` so the item 1.5 factory can do ``BodyPart.make("leg")``.
    _PLUGIN_REGISTRY: Dict[str, Type["BodyPartPlugin"]] = {}

    def __init__(
        self,
        name: Optional[str] = None,
        health_max: Optional[int] = None,
        is_critical: Optional[bool] = None,
        traits: Optional[Dict[DamageTypes, float]] = None,
        exposure: Optional[Dict[Reach, float]] = None,
        debuffs: Optional[Dict[InjuryLevels, Dict[Stat, int]]] = None,
    ):
        # Read class-level defaults off ``type(self)`` so subclasses'
        # overrides are picked up, then allow per-instance kwargs to
        # override the class defaults on a per-field basis.
        cls = type(self)
        resolved_name = name if name is not None else cls.name
        resolved_health_max = (
            health_max if health_max is not None else cls.health_max
        )
        resolved_is_critical = (
            is_critical if is_critical is not None else cls.is_critical
        )
        resolved_traits = traits if traits is not None else dict(cls.traits)
        resolved_exposure = (
            exposure if exposure is not None else dict(cls.exposure)
        )
        resolved_debuffs = (
            debuffs if debuffs is not None else dict(cls.debuffs)
        )

        super().__init__(
            name=resolved_name,
            health_max=resolved_health_max,
            is_critical=resolved_is_critical,
            traits=resolved_traits,
            exposure=resolved_exposure,
            debuffs=resolved_debuffs,
        )

        # Phase B3: plugins that mix in :class:`Equippable` get a
        # fresh per-instance ``placements`` dict keyed by the
        # class-level ``PLACEMENT_KEYS`` declaration. This is the
        # authoritative storage for equipped items — the
        # :attr:`Player.part_equipment` nested-dict view rebuilds
        # itself on access by walking these per-node dicts.
        if isinstance(self, Equippable):
            self.placements: Dict[str, Optional[object]] = {
                key: None for key in type(self).PLACEMENT_KEYS
            }

    # ------------------------------------------------------------------
    # Plugin discovery
    # ------------------------------------------------------------------

    @classmethod
    def load_plugins(cls) -> None:
        """Load all body-part plugin files under :attr:`BASEPATH`.

        Mirrors :meth:`MonsterPlugin.load_plugins` -- delegates filesystem
        discovery to :class:`PluginManager`, which skips ``__init__.py``
        and excludes the base class from the loaded list.

        After loading, the name-keyed ``_PLUGIN_REGISTRY`` is rebuilt from
        ``PluginManager.LOADED_PLUGINS[BodyPartPlugin]`` so lookups via
        :meth:`get_plugin_class` reflect whatever was just discovered.
        """
        PluginManager.load(BodyPartPlugin, BodyPartPlugin.BASEPATH)

        registry: Dict[str, Type["BodyPartPlugin"]] = {}
        for plugin_cls in PluginManager.LOADED_PLUGINS.get(BodyPartPlugin, []):
            key = getattr(plugin_cls, "name", "") or plugin_cls.__name__.lower()
            if key:
                registry[key] = plugin_cls
        BodyPartPlugin._PLUGIN_REGISTRY = registry

    @classmethod
    def get_plugin_class(
        cls, name: str
    ) -> Optional[Type["BodyPartPlugin"]]:
        """Look up a loaded plugin class by its declared ``name``.

        Returns ``None`` if the name is unknown (or if ``load_plugins``
        has never been called). The item 1.5 factory uses this as its
        lookup hook.
        """
        if not name:
            return None
        return BodyPartPlugin._PLUGIN_REGISTRY.get(name)
