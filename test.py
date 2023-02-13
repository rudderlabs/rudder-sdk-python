import unittest
loader = unittest.TestLoader()
tests = loader.discover('rudderstack/analytics/')
testRunner = unittest.runner.TextTestRunner()
testRunner.run(tests)