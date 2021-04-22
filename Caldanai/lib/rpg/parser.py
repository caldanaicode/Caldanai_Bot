import re
from random import choice

class Parser:
	optionsRE = r'\{(?P<options>[^{}]+)\}'
	nounRE = r'\$n'
	commandRE = r'\$c'
	tokenRE = r'\$(?P<token>\w+)'

	@staticmethod
	def parse(input: str, name: str = None, command: str = None) -> str:
		output = input
		
		for match in re.finditer(Parser.optionsRE, output):
			output = re.sub(Parser.optionsRE, choice(match.group('options').split('|')), output, 1)
		
		if name is not None:
			output = re.sub(Parser.nounRE, name, output)
		
		if command is not None:
			output = re.sub(Parser.commandRE, command, output)

		return output