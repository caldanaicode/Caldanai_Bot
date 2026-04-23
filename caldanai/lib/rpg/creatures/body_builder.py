"""Declarative body-tree construction DSL.

Each creature plugin declares its anatomy with a ``BODY_TREE``
expression built from two factories: :func:`node` (one node plus
its subtree) and :func:`paired` (a symmetric left/right pair).
``Creature.__init__`` materializes the spec into live
:class:`Node` instances per instance — the spec itself lives at
class level, but materialization produces fresh objects so two
goblins don't share arm state.

The module is named in homage to Arnold: a *body builder* that
builds bodies.

Usage
-----

Static declaration (covers ~95% of creatures):

.. code-block:: python

    class GoblinPlugin(MonsterPlugin):
        BODY_TREE = node(TorsoPlugin, children=[
            node(NeckPlugin, children=[
                node(HeadPlugin, children=[
                    *paired(EyePlugin, "eye"),
                ]),
            ]),
            *paired(ArmPlugin, "arm"),
            *paired(LegPlugin, "leg"),
        ])

Nested children under a paired anatomy:

.. code-block:: python

    # Each arm carries its own hand subtree.
    *paired(ArmPlugin, "arm",
            children_builder=lambda side: [
                node(HandPlugin, name=f"hand.{side}"),
            ]),

Dynamic body shapes (hydra family, doppelganger) override
``_materialize_body_tree`` on the creature class and return a
built tree directly — see the Phase B1 plan for the full
pattern.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from caldanai.lib.rpg.creatures.node import Node


@dataclass
class _NodeSpec:
    """Lightweight description of one node in a body tree.

    Not a :class:`Node` — just a blueprint. :meth:`build`
    materializes it (and its subtree) into real instances at
    creature-spawn time. Keeping specs immutable data means one
    spec object can safely live at class level and be built
    many times (one per creature instance).
    """

    plugin_class: Type[Node]
    name: Optional[str] = None
    children: List["_NodeSpec"] = field(default_factory=list)
    overrides: Dict[str, Any] = field(default_factory=dict)

    def build(self) -> Node:
        """Materialize this spec (and its subtree) into a live
        :class:`Node` tree. Returns the root node.

        Name-uniqueness is enforced at the tree root — duplicate
        names raise ``ValueError``. The check runs after
        construction so per-instance name overrides from the
        spec are accounted for.
        """
        root = self._build_one(parent=None)
        _assert_unique_names(root)
        return root

    def _build_one(self, parent: Optional[Node]) -> Node:
        kwargs = dict(self.overrides)
        if self.name is not None:
            kwargs["name"] = self.name
        instance = self.plugin_class(**kwargs)
        # The tree primitive owns these fields post-B1; plugins
        # inherit from :class:`Node` so the attributes exist.
        # Paranoid fallback: set them here in case an older
        # BodyPart subclass hasn't picked up the Node base yet
        # during the staged migration.
        if not hasattr(instance, "children") or instance.children is None:
            instance.children = []
        instance.parent = parent
        for child_spec in self.children:
            child = child_spec._build_one(parent=instance)
            instance.children.append(child)
        return instance


def node(
    plugin_class: Type[Node],
    name: Optional[str] = None,
    children: Optional[List[_NodeSpec]] = None,
    **overrides: Any,
) -> _NodeSpec:
    """Declare one node in a body-tree spec.

    :param plugin_class: The plugin class to instantiate at
        build time (``HeadPlugin``, ``ArmPlugin``, etc.). Must
        accept keyword overrides in its constructor.
    :param name: Per-instance name override. When ``None``, the
        plugin class's class-level ``name`` default is used
        (appropriate for singleton parts like ``torso`` or
        ``head``). Required for symmetric anatomy where the
        same plugin class is instantiated twice
        (``"arm.left"`` / ``"arm.right"``).
    :param children: Child specs nested under this node.
    :param overrides: Extra keyword arguments passed to the
        plugin's constructor (e.g. ``health_max=12`` for a
        per-species override of the plugin's default HP).
    """
    return _NodeSpec(
        plugin_class=plugin_class,
        name=name,
        children=list(children) if children else [],
        overrides=dict(overrides),
    )


def paired(
    plugin_class: Type[Node],
    base_name: str,
    children_builder: Optional[Callable[[str], List[_NodeSpec]]] = None,
    **overrides: Any,
) -> List[_NodeSpec]:
    """Emit a symmetric left / right pair of node specs.

    The two specs use the same ``plugin_class`` and
    ``overrides``, differing only in ``name`` (``f"{base_name}.left"``
    and ``f"{base_name}.right"``). When ``children_builder`` is
    supplied, it is invoked once per side with the side string
    (``"left"`` or ``"right"``) and must return that side's
    child specs — letting callers name per-side descendants
    consistently (``hand.left`` under ``arm.left``).

    Returns a ``List[_NodeSpec]`` of length 2; splat-unpack it
    into the parent's ``children`` list with ``*paired(...)``.
    """
    specs: List[_NodeSpec] = []
    for side in ("left", "right"):
        side_name = f"{base_name}.{side}"
        side_children = children_builder(side) if children_builder else None
        specs.append(
            _NodeSpec(
                plugin_class=plugin_class,
                name=side_name,
                children=list(side_children) if side_children else [],
                overrides=dict(overrides),
            )
        )
    return specs


# ----------------------------------------------------------------------
# Canonical anatomy factories
# ----------------------------------------------------------------------
#
# Mirrors the BodyPart.humanoid() / quadruped() / quadruped_winged()
# classmethods: one call produces a ready-to-use ``BODY_TREE`` spec for
# the common monster body shapes. Each call returns a fresh spec so
# mutating one creature's tree never touches another's.


def humanoid_tree() -> _NodeSpec:
    """Standard six-part humanoid body tree.

    Shape: torso → head + paired arms + paired legs. Matches the
    part set the pre-B1 ``BodyPart.humanoid()`` factory produced.
    Monsters with this baseline anatomy (goblin, bandit, skeleton,
    vampire, math-teacher, etc.) declare
    ``BODY_TREE = humanoid_tree()``.

    Note the deliberate asymmetry with :data:`PLAYER_BODY_TREE`
    over in ``player.py``: the player has ``neck`` + paired
    ``eye`` nodes; this helper does not. That mirrors pre-B1
    behavior — ``BodyPart.humanoid()`` never produced neck or
    eyes, while the player's flat ``_DEFAULT_PARTS`` dict added
    them. B1 is purely structural; adding anatomy to monsters
    that didn't have it before would be a gameplay change.
    Per-monster plugins that want richer anatomy (cyclops with
    one eye, pixie with wings) declare their own tree.
    """
    from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
    from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
    from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
    from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin

    return node(TorsoPlugin, name="torso", children=[
        node(HeadPlugin, name="head"),
        *paired(ArmPlugin, "arm"),
        *paired(LegPlugin, "leg"),
    ])


def quadruped_tree() -> _NodeSpec:
    """Standard seven-part quadruped body tree.

    Shape: torso → head + paired forelegs + paired hindlegs +
    tail. Matches the pre-B1 ``BodyPart.quadruped()`` factory.
    """
    from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
    from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
    from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
    from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin

    return node(TorsoPlugin, name="torso", children=[
        node(HeadPlugin, name="head"),
        *paired(LegPlugin, "foreleg"),
        *paired(LegPlugin, "hindleg"),
        node(TailPlugin, name="tail"),
    ])


def quadruped_winged_tree() -> _NodeSpec:
    """Standard nine-part winged quadruped body tree.

    Shape: quadruped + paired wings. Matches the pre-B1
    ``BodyPart.quadruped_winged()`` factory. Dragon, bearowl, and
    other winged quadrupeds start from this.
    """
    from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
    from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
    from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
    from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
    from caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin

    return node(TorsoPlugin, name="torso", children=[
        node(HeadPlugin, name="head"),
        *paired(LegPlugin, "foreleg"),
        *paired(LegPlugin, "hindleg"),
        node(TailPlugin, name="tail"),
        *paired(WingPlugin, "wing"),
    ])


def _assert_unique_names(root: Node) -> None:
    """Raise ``ValueError`` if two nodes in the materialized tree
    share a name. Persistence keys by name, so duplicates would
    collide silently and corrupt per-part state.
    """
    seen: Dict[str, Node] = {}
    for n in root.walk():
        if n.name in seen:
            raise ValueError(
                f"Duplicate node name {n.name!r} in body tree "
                f"(rooted at {root.name!r}); names must be unique "
                f"per creature because persistence keys by name."
            )
        seen[n.name] = n
