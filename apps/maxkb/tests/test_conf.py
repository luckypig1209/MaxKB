from unittest import TestCase

from maxkb.conf import Config


class ConfigDebugTests(TestCase):
    def test_false_like_environment_values_disable_debug(self):
        for value in ("false", "0", "no", "off", "", False, 0):
            with self.subTest(value=value):
                self.assertFalse(Config({"DEBUG": value}).get_debug())

    def test_true_like_environment_values_enable_debug(self):
        for value in ("true", "1", "yes", "on", True, 1):
            with self.subTest(value=value):
                self.assertTrue(Config({"DEBUG": value}).get_debug())
