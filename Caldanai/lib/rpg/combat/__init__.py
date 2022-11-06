from Caldanai.lib.rpg.helpers.enums import DamageTypes


def swing(actor, dmg_type: DamageTypes, dmg_roll: str, victim, target=None):
	if target and target.traits and dmg_type in target.traits:
		multiplier = target.traits[dmg_type]
