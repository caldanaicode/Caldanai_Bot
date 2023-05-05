import functools
import inspect
import re

from Caldanai.Logger import stdout


def bounded(minimum, maximum):
	def decorator(function):
		@functools.wraps(function)
		def wrapper(*args, **kwargs):
			result = function(*args, **kwargs)
			return minimum if result < minimum else maximum if result > maximum else result
		return wrapper
	return decorator

def takes_target(target_types):
	def decorator(function):
		@functools.wraps(function)
		def wrapper(*args, **kwargs):
			if 'target' in kwargs.keys() \
				and kwargs['target'] is not None \
				and isinstance(kwargs['target'], target_types):
				return function(*args, **kwargs)
			return None
		return wrapper
	return decorator

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