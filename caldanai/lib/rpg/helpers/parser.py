import re
from re import Match
from typing import Tuple, List

from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.enums import Pronouns


_log = get_logger(__name__)

actorRegex = re.compile(r"@(?P<actor>\d+)(?P<form>\w*)")
casing = {"c": "capitalize", "l": "lower", "t": "title", "u": "upper"}

forms = {
    "s": Pronouns.SUBJECTIVE,
    "o": Pronouns.OBJECTIVE,
    "p": Pronouns.POSSESSIVE,
    "a": Pronouns.ADJECTIVE,
    "r": Pronouns.REFLEXIVE,
}


def _process(match: Match, actors: Tuple) -> str:
    if match is None:
        return ""

    if len(actors) == 0:
        _log.error(f"Error parsing message for actors. No actors were supplied. {match.groupdict()}")
        return match.group(0)

    m = match.groupdict()
    if m["actor"] and m["actor"].isnumeric() and 0 <= (num := int(m["actor"]) - 1) < len(actors):
        actor = actors[num]
    else:
        actor = actors[0]
    form = m["form"].lower() if m["form"] else ""
    result = actor.name
    for f in form:
        if f == "d":
            # Definite article: "the dragon" for monsters, bare name for named entities.
            if getattr(actor, "uses_article", True):
                result = f"the {result}"
        elif f == "i":
            # Indefinite article: "a dragon" / "an ogre" for monsters, bare name for named entities.
            # Creatures can override with ``indefinite_article`` for phonetic
            # exceptions (e.g., "a unicorn" despite starting with 'u').
            if getattr(actor, "uses_article", True):
                override = getattr(actor, "indefinite_article", None)
                if override:
                    article = override
                else:
                    article = "an" if result and result[0].lower() in "aeiou" else "a"
                result = f"{article} {result}"
        elif f in forms.keys():
            result = actor.pronouns[forms[f]]
        elif f in casing.keys():
            result = result.__getattribute__(casing[f])()

    return result


def parse(msg: str, *actors) -> str:
    """
    Returns a string where placeholders have been replaced with the proper nouns/pronouns/etc.

    :param msg: The string to parse
    :param actors: A tuple containing the actors in the message, ordered by their @ position in the message
    :return: The original string with all @ flags replaced appropriately
    """

    result = actorRegex.sub(lambda m: _process(m, actors), msg)

    return result


def item_list_to_string(items: List) -> str:
    """
    Takes a list of items and returns a comma-separated, English-appropriate string.

    :param items: The list of items to stringify.
    :return: The text representation.
    """

    names = [i.get_full_name() for i in items if i is not None]
    if len(names) > 1:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names)
