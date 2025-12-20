import sys
import io
import warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '.')
from scripts.test_force_params_mock import TestMaskServiceForcedParams
import unittest

suite = unittest.TestLoader().loadTestsFromTestCase(TestMaskServiceForcedParams)
runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
