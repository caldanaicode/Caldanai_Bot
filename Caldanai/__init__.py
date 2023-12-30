import functools
import inspect
import re

from Caldanai.Logger import stdout

import asyncio


class Observer:
	"""A simple Observer class intended for inheritance. Allows receiving updates from any Subject."""
	async def update(self, message):
		"""Receives an update from a subject."""
		raise NotImplementedError


class Subject:
	"""A simple Subject class intended for inheritance. Provides functionality for attaching, detaching, and notifying Observers."""
	def __init__(self):
		self._observers: set[Observer] = set()
	
	def attach(self, observer):
		"""Attaches an observer to the list of observers."""
		self._observers.add(observer)
	
	def detach(self, observer):
		"""Removes an observer from the list of observers."""
		self._observers.remove(observer)
	
	async def notify(self, message):
		"""Sends a message to all observers."""
		await asyncio.gather(*(observer.update(message) for observer in self._observers))


def debug_print(func):
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		def set_and_print(name, value):
			nonlocal locals_dict
			locals_dict[name] = value
			stdout(f'{name} = {value}')

		src = inspect.getsource(func)
		modified = re.sub(r'(\s*)(\w+)\s*=\s*(.+)', r'\1set_and_print("\2", \3)', src)
		globals_dict = func.__globals__.copy()
		globals_dict['set_and_print'] = set_and_print
		locals_dict = {}
		stdout(f"Debug printing {func.__name__}")
		exec(modified, globals_dict, locals_dict)
		return func(*args, **kwargs, **locals_dict)
	return wrapper

# def bounded(minimum, maximum):
# 	def decorator(function):
# 		@functools.wraps(function)
# 		def wrapper(*args, **kwargs):
# 			result = function(*args, **kwargs)
# 			return minimum if result < minimum else maximum if result > maximum else result
# 		return wrapper
# 	return decorator

# def takes_target(target_types):
# 	def decorator(function):
# 		@functools.wraps(function)
# 		def wrapper(*args, **kwargs):
# 			if 'target' in kwargs.keys() \
# 				and kwargs['target'] is not None \
# 				and isinstance(kwargs['target'], target_types):
# 				return function(*args, **kwargs)
# 			return None
# 		return wrapper
# 	return decorator