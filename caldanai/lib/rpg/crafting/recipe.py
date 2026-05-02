"""Recipe plugin base + discovery.

Mirrors the monsters-and-armor plugin pattern (one Python file
per recipe, declarative class-attributes, discovery walks the
``crafting/recipes/<set>/<stem>.py`` tree). Recipes live OUTSIDE
``inventory/`` because they're not items — they're metadata
about how items combine to produce other items.
"""
import importlib
from glob import glob
from os import path as _ospath
from typing import Dict, List, Optional, Type

from caldanai.logger import get_logger


_log = get_logger(__name__)


# Global registry: output stem → RecipePlugin subclass. Populated
# by :func:`discover_recipes` walking the recipes tree.
RECIPES: Dict[str, Type["RecipePlugin"]] = {}


class RecipePlugin:
    """Base class for recipe plugins.

    Subclass attributes (override per-recipe):

    - :attr:`output` — plugin stem of the crafted item (e.g.
      ``"leather_jerkin"``). Resolved through ``Inventory.load_item``.
    - :attr:`materials` — ``{material_plugin_stem: count}``. Each
      material is a Stackable plugin in the inventory tree.
    - :attr:`skill` — skill name used for the success / quality
      rolls (e.g. ``"leatherworking"``). ``None`` for unskilled.
    - :attr:`min_skill` — minimum skill XP required to attempt.
      Below this, the craft is refused outright.
    - :attr:`requires_known` — when True, the recipe must be in
      ``player.known_recipes`` before craft is allowed. Used for
      learn-from-scroll recipes; basic recipes leave this False.
    - :attr:`xp_reward_success` / :attr:`xp_reward_failure` —
      skill XP granted per attempt. Failures still grant some
      so the player isn't grinding-blocked by bad luck.

    Subclasses can override :meth:`on_craft` to inject custom
    side-effects (special flavor text, multi-output recipes,
    consume non-material inventory items). The default reads
    :attr:`output` and lets the cog generate the item via
    ``Inventory.load_item``.
    """

    output: str = ""
    materials: Dict[str, int] = {}
    skill: Optional[str] = None
    min_skill: int = 0
    requires_known: bool = False
    # Per-attempt XP BASE. The actual amount granted is scaled by
    # the player's current skill level via
    # ``Player.register_craft_xp``: success grants
    # ``xp_reward_success + floor(10 * sqrt(level))``, failure
    # grants the flat ``xp_reward_failure`` (mirrors combat misses).
    #
    # Tuned 2026-05-02 from community feedback (Celowin: prior 5/2
    # flat values made leatherworking 1→2 a 286-attempt grind).
    # Base 20/5 + sqrt-level scaling targets ~50/60/85/105 attempts
    # per level for L1→L5, holding steady against the quadratic
    # level threshold (combat skills reuse the same general shape
    # via ``Player.register_attack_xp``).
    xp_reward_success: int = 20
    xp_reward_failure: int = 5

    @classmethod
    def display_name(cls) -> str:
        """Human-readable label for ``$craft list`` and friends.
        Defaults to the output stem with underscores → spaces."""
        return cls.output.replace("_", " ")


def discover_recipes() -> None:
    """Walk ``caldanai/lib/rpg/crafting/recipes/`` and register
    every plugin file in :data:`RECIPES` keyed by ``output`` stem.

    Idempotent — re-running clears and rebuilds the registry, so
    test fixtures and live discovery stay in sync. Subclasses that
    don't set :attr:`output` are skipped (defensive: the base
    class itself shouldn't register).
    """
    RECIPES.clear()

    recipes_root = _ospath.join(_ospath.dirname(__file__), "recipes")
    pattern = _ospath.join(recipes_root, "**", "*.py")
    for filepath in glob(pattern, recursive=True):
        stem = _ospath.basename(filepath)[:-3]
        if stem == "__init__":
            continue

        rel = _ospath.relpath(filepath, recipes_root)
        module_path = (
            "caldanai.lib.rpg.crafting.recipes."
            + rel[:-3].replace(_ospath.sep, ".")
        )
        try:
            mod = importlib.import_module(module_path)
        except Exception as e:
            _log.error(f"Unable to import recipe {module_path}: {e}")
            continue

        plugin_cls = getattr(mod, "RecipePlugin", None)
        if plugin_cls is None or not isinstance(plugin_cls, type):
            continue
        if not issubclass(plugin_cls, RecipePlugin):
            continue
        # Footgun: if a recipe file imports the base directly with
        # ``from ... import RecipePlugin`` instead of ``as _Base``,
        # the module's ``RecipePlugin`` symbol resolves to the base
        # class itself — discovery would silently skip it on the
        # ``not output`` check below. Warn loudly so the typo
        # surfaces.
        if plugin_cls is RecipePlugin:
            _log.warning(
                f"Recipe file {module_path} re-exports the base "
                f"RecipePlugin without subclassing — recipe will "
                f"not register. Use ``from caldanai.lib.rpg.crafting "
                f"import RecipePlugin as _Base`` and subclass _Base."
            )
            continue
        if not plugin_cls.output:
            continue

        if plugin_cls.output in RECIPES:
            _log.warning(
                f"Duplicate recipe output '{plugin_cls.output}' — "
                f"{module_path} shadowed."
            )
            continue
        RECIPES[plugin_cls.output] = plugin_cls


def get_recipe(output_stem: str) -> Optional[Type[RecipePlugin]]:
    """Resolve an output stem to its recipe class. Calls
    :func:`discover_recipes` lazily on first miss so callers
    don't need to bootstrap manually."""
    if output_stem in RECIPES:
        return RECIPES[output_stem]
    if not RECIPES:
        discover_recipes()
    return RECIPES.get(output_stem)


def list_recipes() -> List[Type[RecipePlugin]]:
    """Return every registered recipe class in stem-sorted order."""
    if not RECIPES:
        discover_recipes()
    return [RECIPES[k] for k in sorted(RECIPES.keys())]
