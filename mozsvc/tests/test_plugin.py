import unittest
from StringIO import StringIO
from textwrap import dedent

from zope.interface import Interface, implements
from zope.interface.verify import verifyObject

from pyramid.config import Configurator, ConfigurationConflictError

from mozsvc.config import Config
from mozsvc.plugin import load_and_register


class ITest1(Interface):
    """A test Interface."""
    pass


class ITest2(Interface):
    """Another test Interface."""
    pass


class Test1(object):
    """A concrete implementation of ITest1."""
    implements(ITest1)

    def __init__(self, **kwds):
        self.kwds = kwds


class Test2(object):
    """A concrete implementation of ITest2."""
    implements(ITest2)

    def __init__(self, **kwds):
        self.kwds = kwds


class Test1And2(object):
    """A concrete implementation of both ITest1 and ITest2."""
    implements(ITest1, ITest2)

    def __init__(self, **kwds):
        self.kwds = kwds


class TestPluginLoading(unittest.TestCase):

    def test_loading_from_config(self):
        config = Config(StringIO(dedent("""
        [test1]
        backend = mozsvc.tests.test_plugin.Test1
        arg1 = 1
        hello = world
        [test2]
        dontusethis =  seriously
        """)))
        settings = {"config": config}
        config = Configurator(settings=settings)
        plugin = load_and_register("test1", config)
        config.commit()
        self.failUnless(verifyObject(ITest1, plugin))
        self.failUnless(isinstance(plugin, Test1))
        self.assertEquals(plugin.kwds["arg1"], 1)
        self.assertEquals(plugin.kwds["hello"], "world")
        self.assertEquals(len(plugin.kwds), 2)
        self.failUnless(config.registry.queryUtility(ITest1) is plugin)

    def test_loading_from_settings(self):
        settings = {
          "test1.backend": "mozsvc.tests.test_plugin.Test1",
          "test1.arg1": 1,
          "test1.hello": "world",
          "test2.dontusethis": "seriously"
        }
        config = Configurator(settings=settings)
        plugin = load_and_register("test1", config)
        config.commit()
        self.failUnless(verifyObject(ITest1, plugin))
        self.failUnless(isinstance(plugin, Test1))
        self.assertEquals(plugin.kwds["arg1"], 1)
        self.assertEquals(plugin.kwds["hello"], "world")
        self.assertEquals(len(plugin.kwds), 2)
        self.failUnless(config.registry.queryUtility(ITest1) is plugin)

    def test_loading_several_plugins(self):
        settings = {
          "test1.backend": "mozsvc.tests.test_plugin.Test1",
          "test1.hello": "world",
          "test2.backend": "mozsvc.tests.test_plugin.Test2",
        }
        config = Configurator(settings=settings)
        plugin1 = load_and_register("test1", config)
        plugin2 = load_and_register("test2", config)
        config.commit()

        self.failUnless(verifyObject(ITest1, plugin1))
        self.failUnless(isinstance(plugin1, Test1))
        self.assertEquals(plugin1.kwds["hello"], "world")
        self.assertEquals(len(plugin1.kwds), 1)
        self.failUnless(config.registry.queryUtility(ITest1) is plugin1)

        self.failUnless(verifyObject(ITest2, plugin2))
        self.failUnless(isinstance(plugin2, Test2))
        self.assertEquals(len(plugin2.kwds), 0)
        self.failUnless(config.registry.queryUtility(ITest2) is plugin2)

    def test_loading_with_conflict_detection(self):
        settings = {
          "test1.backend": "mozsvc.tests.test_plugin.Test1",
          "test_both.backend": "mozsvc.tests.test_plugin.Test1And2",
        }
        config = Configurator(settings=settings)
        load_and_register("test1", config)
        load_and_register("test_both", config)
        self.assertRaises(ConfigurationConflictError, config.commit)

    def test_loading_with_conflict_resolution(self):
        settings = {
          "test1.backend": "mozsvc.tests.test_plugin.Test1",
          "test2.backend": "mozsvc.tests.test_plugin.Test2",
          "test_both.backend": "mozsvc.tests.test_plugin.Test1And2",
        }

        # Load plugin_both last, it will win for both interfaces.
        config = Configurator(settings=settings, autocommit=True)
        load_and_register("test1", config)
        plugin2 = load_and_register("test2", config)
        plugin_both = load_and_register("test_both", config)
        self.failUnless(config.registry.queryUtility(ITest1) is plugin_both)
        self.failUnless(config.registry.queryUtility(ITest2) is plugin_both)

        # Load plugin_both before plugin2, it will be beaten only for that.
        config = Configurator(settings=settings, autocommit=True)
        load_and_register("test1", config)
        plugin_both = load_and_register("test_both", config)
        plugin2 = load_and_register("test2", config)
        self.failUnless(config.registry.queryUtility(ITest1) is plugin_both)
        self.failUnless(config.registry.queryUtility(ITest2) is plugin2)
