import re
from re import Match
from typing import Tuple, List

from Caldanai.Logger import get_logger
from Caldanai.lib.rpg.helpers.enums import Pronouns


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
        return None

    if len(actors) == 0:
        _log.error(f"Error parsing message for actors. No actors were supplied. {match.groupdict()}")
        return None

    m = match.groupdict()
    if m["actor"] and m["actor"].isnumeric() and 0 <= (num := int(m["actor"]) - 1) < len(actors):
        actor = actors[num]
    else:
        actor = actors[0]
    form = m["form"].lower() if m["form"] else ""
    result = actor.name
    for f in form:
        if f in forms.keys():
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
