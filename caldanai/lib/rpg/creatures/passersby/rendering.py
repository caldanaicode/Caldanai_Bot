"""Render-layer helpers for passerby flavor pools.

Why this exists
---------------

Passerby flavor pools are authored as if the NPC is fully
acquainted with whoever they're addressing — references use
``@1`` for the actor (player) freely. Reality is usually
otherwise: an NPC may be a complete stranger, a friend who knows
the player's name, or somewhere in between. To avoid forcing
authors to write 2× pools (one for stranger, one for acquainted)
this layer substitutes a :class:`StrangerActor` wrapper for the
real player when the NPC doesn't know their name.

Plus a per-NPC :attr:`PasserbyPlugin.NAMING_BIAS` adds texture: an
acquainted NPC may STILL use the generic surface most of the time
if their character voice prefers it (the herbalist's mostly-
"traveler" register; rare name-use lands as deliberate weight).
The bias rolls once per line so a single rendered string is
internally consistent — never "@1d ... @1np" rendering as
"Caels ... the traveler's" mid-sentence.

The three render helpers map to the three shapes of passerby
pools:

- :func:`render_npc_only` — pools that reference only the NPC
  (arrival, ambient, departure, silhouette). No StrangerActor
  needed.
- :func:`render_combat_witness` — pools that reference the NPC
  + a representative party member (combat-won / combat-fled /
  party-death). The witness gets the StrangerActor treatment.
- :func:`render_actor_npc` — pools where a player is the actor
  and the NPC is the target (social reactions, depart-when-
  pushed, flee-from-attack). Player gets the StrangerActor
  treatment.
"""

from random import random
from typing import Any, Optional

from caldanai.lib.rpg.helpers.parser import parse


class StrangerActor:
    """Wraps a real :class:`Player` (or other Creature) but renames
    them ``"traveler"`` for parser substitution when the NPC doesn't
    know who they are.

    Pronouns and verb-agreement pass through from the wrapped
    creature so the NPC never mis-genders a stranger — only the
    ``.name`` surface is masked. Other attributes (`.user_id`,
    ``.uses_article``, etc.) are proxied so token forms like
    ``@1m`` (Discord mention) still resolve to the real player.

    Also overrides ``uses_article = True`` regardless of the wrapped
    actor's value so ``@1d`` renders ``"the traveler"`` cleanly
    (Players normally have ``uses_article = False`` because their
    name IS their identity; for the stranger surface the article
    is what makes "traveler" read as a role rather than a proper
    noun).

    Mention tokens (``@1m``) deliberately STILL emit the real
    user_id mention. The stranger surface masks the rendered
    name in prose but a mention is mechanical — the player who
    needs to be pinged is still the player who needs to be
    pinged. NPCs don't have ``user_id``, so this matters only
    for the actor-side wrap (player addressing NPC); NPCs as
    targets aren't wrapped.
    """

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped

    @property
    def name(self) -> str:
        return "traveler"

    @property
    def uses_article(self) -> bool:
        return True

    def __getattr__(self, attr: str) -> Any:
        # Fallback for everything else — pronouns, user_id,
        # is_dead, plural_verbs, etc. Called only when the
        # attribute isn't found on StrangerActor itself, so the
        # ``name`` and ``uses_article`` overrides above take
        # precedence.
        return getattr(self._wrapped, attr)


def _maybe_unwrap(actor: Any, *, acquainted: bool, naming_bias: float) -> Any:
    """Decide between the real actor and a :class:`StrangerActor`
    wrap based on acquaintance + the per-NPC name-use bias.

    - Not acquainted → always wrap (stranger surface).
    - Acquainted → roll once: with probability ``naming_bias`` use
      the real actor (full name); else wrap.

    The single roll is critical for line-level consistency — every
    ``@1`` reference in a single rendered line resolves to the
    same surface. Re-rolling per token would smear "Caels" and
    "the traveler" within one sentence.
    """
    if not acquainted or random() >= naming_bias:
        return StrangerActor(actor)
    return actor


def render_npc_only(line: str, npc: Any) -> str:
    """Render a pool line whose only actor is the NPC themselves
    (arrival / ambient / departure / silhouette). No acquaintance
    or bias logic — these lines never reference a player."""
    return parse(line, npc)


def render_combat_witness(
    line: str,
    npc: Any,
    witness: Any,
    *,
    acquainted: bool,
    naming_bias: float,
) -> str:
    """Render a combat-resolved reaction line. ``@1`` = NPC,
    ``@2`` = the witness party member (killing-blow dealer, alive
    survivor, or fallen player). The witness gets the StrangerActor
    treatment based on whether the NPC knows them; the NPC always
    renders as themselves (they're the speaker, not the addressee).
    """
    if witness is None:
        return parse(line, npc)
    target = _maybe_unwrap(
        witness, acquainted=acquainted, naming_bias=naming_bias,
    )
    return parse(line, npc, target)


def render_actor_npc(
    line: str,
    actor: Any,
    npc: Any,
    *,
    acquainted: bool,
    naming_bias: float,
) -> str:
    """Render an actor-driven line where ``@1`` = the player who
    used the verb (wave / nod / greet / push / attack) and
    ``@2`` = the NPC. The player gets the StrangerActor wrap
    based on the NPC's acquaintance with them. The NPC always
    renders as themselves.
    """
    actor_resolved = _maybe_unwrap(
        actor, acquainted=acquainted, naming_bias=naming_bias,
    )
    return parse(line, actor_resolved, npc)


def force_stranger(actor: Any) -> StrangerActor:
    """Helper for callers that want the StrangerActor surface
    without the bias roll — e.g. a one-off line that should
    always read as a stranger gesture regardless of acquaintance.
    Most rendering should go through :func:`_maybe_unwrap`."""
    return StrangerActor(actor)
