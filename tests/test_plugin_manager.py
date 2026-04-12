"""Regression tests for ``Caldanai.PluginManager``.

These tests protect against a latent bug where ``PluginManager.load``
used ``importlib.util.spec_from_file_location`` + ``exec_module`` without
registering the freshly-created module in ``sys.modules``. That omission
caused downstream ``from <pkg> import SomeClass`` statements to re-run
the module body and produce a *second* class object, so
``isinstance(instance, SomeClass)`` — and class-identity comparisons —
would unexpectedly return False / be non-identical.

The canonical Python pattern (per the importlib docs) is to insert the
module into ``sys.modules`` *before* calling ``exec_module``, which is
also necessary for circular-import safety.
"""

from Caldanai import PluginManager
from Caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from Caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin


def test_plugin_manager_uses_sys_modules_so_direct_imports_return_same_class():
    """A class loaded via ``PluginManager.load`` must be *identical* to
    the same class imported normally. If ``PluginManager.load`` fails to
    register the loaded module in ``sys.modules``, a later
    ``from ... import HeadPlugin`` will re-execute the module body and
    create a second, non-identical class object.
    """
    BodyPartPlugin.load_plugins()
    loaded_classes = PluginManager.LOADED_PLUGINS[BodyPartPlugin]
    loaded_head = next(
        (c for c in loaded_classes if c.__name__ == "HeadPlugin"),
        None,
    )
    assert loaded_head is not None, (
        "HeadPlugin was not discovered by BodyPartPlugin.load_plugins()"
    )
    assert loaded_head is HeadPlugin, (
        "PluginManager.load produced a HeadPlugin class that is not "
        "identical to the directly-imported HeadPlugin. This indicates "
        "the loaded module was not registered in sys.modules before "
        "exec_module, causing a duplicate module/class to be created."
    )
