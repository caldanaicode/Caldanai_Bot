import re
from re import Match
from typing import Tuple

from Caldanai.lib.rpg.helpers.enums import Pronouns

actorRegex = re.compile(r'@(?P<actor>\d+)(?P<form>\w*)')
casing = {
	'c': 'capitalize',
	'l': 'lower',
	't': 'title',
	'u': 'upper'
}

forms = {
	's': Pronouns.SUBJECTIVE,
	'o': Pronouns.OBJECTIVE,
	'p': Pronouns.POSSESSIVE,
	'a': Pronouns.ADJECTIVE,
	'r': Pronouns.REFLEXIVE
}


def _process(match: Match, actors: Tuple) -> str:
	if match is None:
		return None

	m = match.groupdict()
	if m['actor'] and m['actor'].isnumeric():
		num = int(m['actor']) - 1
		actor = actors[num]
	else:
		actor = actors[0]
	form = m['form'].lower() if m['form'] else ''
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

	result = msg
	while match := actorRegex.search(result):
		result = actorRegex.sub(_process(match, actors), result, 1)

	return result
