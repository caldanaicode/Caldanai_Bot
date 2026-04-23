"""The tree-primitive shared by every anatomical part.

Phase B1 introduces ``Node`` as the structural ancestor of every
body part. Today's :class:`BodyPart` becomes ``Node`` + combat
mechanics (health, injuries, exposure, debuffs); tomorrow's mixins
(Offensive / Sensory / Mobility / Defensive / Equippable, per the
Phase B plan) layer capabilities onto the same primitive.

Contract this class owns
------------------------

- **Identity.** ``name`` is stable and unique within a creature.
  Used as the key for per-instance persistence
  (``body_parts_health``) and placement lookup
  (``part_equipment``).
- **Hierarchy.** ``parent`` points at the containing node (None
  at the tree root); ``children`` is the list of direct
  descendants. The tree builder (:mod:`body_builder`) wires
  these up at materialization time.
- **Traversal.** :meth:`walk` yields the subtree depth-first.
  :meth:`find` does an exact-name lookup.
- **Reachability.** :meth:`is_reachable` walks the parent chain —
  a node is reachable iff every ancestor is not destroyed AND
  the node itself is not destroyed. This is the one behavioral
  change Phase B1 earns: a destroyed arm makes the hand
  unreachable for targeting even when the hand's own health is
  full.

What this class deliberately does NOT own
-----------------------------------------

Health, injury levels, stat modifiers, exposure tables, damage
routing, hooks — all of that lives on :class:`BodyPart` (and its
plugin subclasses) because those concerns are combat-specific.
``Node.is_destroyed()`` has a default ``False`` return so the
tree primitive can be walked by non-combat code without dragging
combat machinery in.
"""

from typing import Iterator, List, Optional


class Node:
    """One node in a creature's body tree.

    Subclasses layer additional behavior (combat mechanics on
    :class:`BodyPart`; capability mixins post-B2). This base
    stays narrow: identity, hierarchy, traversal, reachability.
    """

    def __init__(
        self,
        name: str = "",
        parent: Optional["Node"] = None,
    ):
        self.name: str = name
        self.parent: Optional[Node] = parent
        self.children: List[Node] = []

    # ------------------------------------------------------------------
    # Tree wiring
    # ------------------------------------------------------------------

    def add_child(self, child: "Node") -> "Node":
        """Attach ``child`` as a direct descendant. Sets the
        child's ``parent`` pointer to ``self`` and appends to
        ``self.children``. Returns the attached child for
        chaining convenience.

        The tree builder uses this at materialization time.
        Runtime mutation (e.g. hydra head regrowth) should go
        through :meth:`Creature.add_body_part` so the flat
        ``body_parts`` view stays in sync with the tree.
        """
        child.parent = self
        self.children.append(child)
        return child

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def walk(self) -> Iterator["Node"]:
        """Depth-first iteration over ``self`` and all descendants.

        Stable ordering: parent first, then each child's subtree
        in declaration order. Flat views over a body tree rely on
        this ordering — don't reorder without auditing the flat-
        view consumers.
        """
        yield self
        for child in self.children:
            yield from child.walk()

    def find(self, name: str) -> Optional["Node"]:
        """Exact-name lookup anywhere in the subtree rooted at
        ``self``. Returns ``None`` if no match.
        """
        for n in self.walk():
            if n.name == name:
                return n
        return None

    def ancestors(self) -> Iterator["Node"]:
        """Walk from ``self.parent`` up to the root. Does not
        yield ``self``.
        """
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    # ------------------------------------------------------------------
    # Reachability
    # ------------------------------------------------------------------

    def is_destroyed(self) -> bool:
        """Default: a bare ``Node`` is never destroyed. Subclasses
        that track damage (:class:`BodyPart` onward) override this
        to consult their health state.
        """
        return False

    def is_reachable(self) -> bool:
        """A node is reachable iff it is not destroyed AND no
        ancestor is destroyed.

        Rationale: destroying a middle node (arm) should make
        everything attached to it (hand, fingers) functionally
        unreachable — you can't target what's dangling off a
        ruined limb. The root is always reachable unless the
        root itself is destroyed.

        O(depth); realistic anatomies are <10 deep so this is
        effectively free.
        """
        if self.is_destroyed():
            return False
        for ancestor in self.ancestors():
            if ancestor.is_destroyed():
                return False
        return True
