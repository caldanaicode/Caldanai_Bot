"""The narrator's own verb-receiver — a :class:`VerbResponder` for
mentions that resolve to the bot itself.

Why this is its own class: the bot isn't a :class:`Player` (no game
state, no warmth pref, no inventory) but it IS a thing players
@-mention with social verbs. Pre-unified-dispatch, the bot-mention
case lived as a per-cog special branch:

.. code-block:: python

    if self.bot.user in mentions:
        Dispatcher.add(channel, _BOT_MENTION_REPLIES.get(cmd, ...))
        return

That branch repeated across every social-cog command. Lifting it
to a real responder lets the unified verb dispatcher route bot-
mentions through the same ``handle_verb`` channel that
StaticObjects, Passersby, Monsters, and Players use, with the
scripted-reply data colocated in this class.

What it handles:

- **Per-verb scripted replies** for the ~13 warmth-aware social
  verbs ($hug, $high_five, $fistbump, $salute, $comfort, $poke,
  $nod, $glare, $shank, $tickle, $taunt, $wink, $wave, $greet).
- **$hug's special-case bot reply** — 3 random lines with a 25%
  HAL gif. File dispatch happens inline; ``handle_verb`` returns
  ``""`` (consumed-silent) so the unified dispatcher doesn't
  double-render.
- **Generic fallback** for verbs without a scripted reply —
  "You cannot share physical gestures with the narrator, mortal."

Not a singleton — instantiated per-mention by the dispatcher. The
class carries no per-instance state today (no warmth, no slot in
``game.player_manager.players``, etc.), so a fresh instance per
verb is fine. If the narrator ever grows mood / state later
(e.g. "the narrator is tired today"), put it on the class or in
a small registry; don't make instances stateful in a way that
relies on a single shared object.
"""

from random import randint
from typing import Any, Optional

from discord import File

from caldanai.dispatcher import Dispatcher


# Per-verb scripted replies. Lookup-by-verb-name, defaults to a
# generic "narrator beyond gestures" line. Co-located here so
# adding a new verb only requires a key here (alongside the
# narration pools / dead-flavor entries in the social cog).
_BOT_MENTION_REPLIES = {
    "high_five": "You cannot slap palms with the narrator, mortal.",
    "fistbump":  "You cannot bump knuckles with the narrator, mortal.",
    "salute":    "The narrator acknowledges the courtesy but is beyond the reach of salutes.",
    "comfort":   "The narrator appreciates the thought, but requires no comforting.",
    "poke":      "One does not simply poke the narrator, mortal.",
    "nod":       "The narrator returns a cosmic, unrenderable nod.",
    "glare":     "You glare at the sky. The sky is unmoved.",
    "shank":     "The narrator cannot be shanked, mock- or otherwise.",
    "tickle":    "The narrator is beyond tickling, thank you for trying.",
    "taunt":     "The narrator is above your petty mockery, mortal.",
    "wink":      "The narrator winks back, somewhere beyond the veil.",
    "wave":      "The narrator waves back from beyond the veil.",
    "greet":     "The narrator acknowledges the introduction, but is unfortunately beyond the reach of new acquaintances.",
    "thank":     "The narrator accepts your thanks with grave, cosmic dignity. (You're welcome.)",
    # Presence verbs — narrator is the lean / the sit / etc.
    # Voice register: dry, weighted, slightly amused at the
    # category error of trying to share a body-in-space with
    # something that has no body.
    "lean":      "The narrator does not lean. The narrator IS the lean.",
    "sit":       "The narrator sits beyond the chair, beyond the room, beyond the having-of-rooms.",
    "rest":      "The narrator rests in the way the sky rests — which is to say, not at all and constantly.",
    "ponder":    "The narrator was already pondering you, mortal. Carry on.",
    "tend":      "The narrator requires no tending. The narrator IS the tending.",
    "bite":      "The narrator cannot be bitten, and gently declines the gesture.",
}


# $hug bot replies — three random lines plus a 1-in-4 HAL gif.
_HUG_BOT_REPLIES = [
    "Get your filthy paws off me, you damned dirty ape!",
    "You cannot hug me, for I exist only in the ether.",
    "One does not simply hug the AI, mortal.",
]


class BotResponder:
    """The narrator's mention-receiver. Implements the
    :class:`VerbResponder` Protocol so the unified verb dispatcher
    can route bot-mentions uniformly.

    Use via the dispatcher's mention-path: when ``mention ==
    ctx.bot.user``, the dispatcher resolves to a ``BotResponder``
    instance and calls ``handle_verb``. The cog command bodies
    don't need to special-case bot mentions anymore.
    """

    def __init__(self, channel=None):
        """``channel`` is the Discord channel used for the $hug
        HAL-gif file dispatch. Stored on the instance because
        ``handle_verb`` doesn't otherwise have channel access
        without ``game.channel`` traversal — and the gif case
        uses ``Dispatcher.add(channel, file=...)`` which needs
        the literal channel object."""
        self._channel = channel

    def matches_token(self, token: str) -> bool:
        """Bot doesn't match text tokens — only direct @-mentions
        resolve here. Always returns ``False`` so the token-chain
        walk skips this responder. Mentions are routed via the
        dispatcher's mention path, not the resolver chain.
        """
        return False

    def handle_verb(
        self,
        verb: str,
        game: Any,
        actor: Any,
        *,
        invocation: str = "",
        **kwargs,
    ) -> Optional[str]:
        """Render the scripted bot-mention reply for ``verb``.

        Returns:

        - ``""`` (consumed-silent) for $hug, where the file
          dispatch happens inline here. The unified dispatcher
          won't render anything additional.
        - The scripted reply string for other verbs, dispatched by
          the unified verb dispatcher in the normal path.
        """
        if verb == "hug":
            channel = self._channel or getattr(game, "channel", None)
            if (c := randint(0, 3)) == 3:
                file = File(
                    f"./site/static/images/hal9000.gif",
                    filename="hal9000.gif",
                )
                Dispatcher.add(channel, file=file)
            else:
                Dispatcher.add(channel, _HUG_BOT_REPLIES[c])
            return ""  # consumed-silent — file/text already dispatched

        return _BOT_MENTION_REPLIES.get(
            verb,
            "You cannot share physical gestures with the narrator, mortal.",
        )
