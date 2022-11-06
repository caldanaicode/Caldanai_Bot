import functools


def bounded(minimum, maximum):
	def decorator(function):
		@functools.wraps(function)
		def wrapper(*args, **kwargs):
			result = function(*args, **kwargs)
			return minimum if result < minimum else maximum if result > maximum else result
		return wrapper
	return decorator
