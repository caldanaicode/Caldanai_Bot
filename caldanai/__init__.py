import asyncio

from abc import ABC, abstractmethod
from caldanai.logger import get_logger
from glob import glob
import importlib
import os
import sys
import traceback
from typing import Dict, List, Type

_log = get_logger(__name__)


class Event:
    """A simple Event class intended for inheritance. Provides an expected interface for Subjects to publish so that Observers can respond."""

    def __init__(self, name: str, data: dict = {}):
        self._name = name
        self._data = data
        _log.debug(f"{name} created")

    @property
    def name(self):
        """Returns the name of the event"""
        return self._name

    @property
    def data(self):
        """Any data associated with the event"""
        return self._data


class Observer(ABC):
    """A simple Observer class intended for inheritance. Allows receiving updates from any Subject."""

    @abstractmethod
    async def on_notify(self, event: Event):
        """Responds to an update from a subject."""
        raise NotImplementedError


class Subject:
    """A simple Subject class intended for inheritance. Provides functionality for attaching, detaching, and notifying Observers."""

    def __init__(self, *args, **kwargs):
        self._observers: set[Observer] = set()
        """The list of objects observing this Subject"""

        super().__init__(*args, **kwargs)

    def attach(self, observer: Observer):
        """Attaches an observer to the list of observers."""
        self._observers.add(observer)

    def detach(self, observer: Observer):
        """Removes an observer from the list of observers."""
        self._observers.remove(observer)

    async def notify(self, event: Event):
        """Sends a message to all observers."""
        await asyncio.gather(*[observer.on_notify(event) for observer in self._observers])


class PluginManager:
    """
    Provides features for loading plugins of any type dynamically at run-time.
    """

    LOADED_PLUGINS: Dict[Type, List[Type]] = {}
    """
    A mapping of plugin base type to the list of types which were loaded.
    """

    @staticmethod
    def load(
            base_type: Type,
            base_path: str,
            ignore_init: bool = True) -> List[Type]:
        """
        Loads (or reloads) plugins of matching the given type from the
        provided path.

        Arguments:
            base_type (Type) - The type (base class) of the plugin to load.

            base_path (str) - The filepath to the plugins directory as \
                recognized via Python module. For example, assume that \
                plugin files are located in './path/to/my/plugins/*.py',\
                where this path is relative to the app's working directory.\
                Also assume that each directory contains an `__init__.py` \
                file in accordance with Python module standards. In this \
                scenario, base_path would be 'path/to/my/plugins'

            ignore_init (bool) - Whether the plugin directory's `__init__.py`\
                file will be ignored. This defaults to True, with the \
                assumption that the plugin's base_type is defined in this \
                file, and does not change frequently. Set this to False if \
                there are plugins located in the same file.

        Return:
            List[Type] - The list of classes that successfully loaded.
        """
        loaded = []
        for filepath in glob(f".{os.sep}{base_path}{os.sep}*.py"):
            if '__init__' in filepath and ignore_init:
                continue

            try:
                module_name = (
                    f"{base_path}."
                    f"{os.path.splitext(os.path.basename(filepath))[0]}")\
                    .replace(os.sep, '.')
                _log.debug(f'Loading plugin module "{module_name=}"')
                if module_name in sys.modules:
                    module = sys.modules[module_name]
                else:
                    spec = importlib.util.spec_from_file_location(
                        module_name,
                        filepath)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                for item_name in dir(module):
                    item = getattr(module, item_name)
                    if isinstance(item, type) \
                            and issubclass(item, base_type) \
                            and item is not base_type:
                        loaded.append(item)
                        _log.info(
                            f"Plugin loaded: {item_name}<{base_type.__name__}>"
                        )
            except Exception:
                _log.error(
                    f"Error loading plugin at '{filepath}': "
                    f"{traceback.format_exc()}")

        PluginManager.LOADED_PLUGINS[base_type] = loaded
        _log.info(f"{len(loaded)} plugins loaded")
        return loaded

