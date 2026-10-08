import math
import unittest

from storm2flow.validation import reference_cdf, hydrology_case


class ValidationOracleTests(unittest.TestCase):
    def test_closed_reference_values(self):
        self.assertAlmostEqual(reference_cdf(1, 1, 1), 1-math.exp(-1))
        self.assertAlmostEqual(reference_cdf(1, 2, 1), 1-2*math.exp(-1))
        # Fractional shape must be independently integrated, not rounded.
        self.assertAlmostEqual(reference_cdf(1, 2.5, 1), .15085496391539038, places=10)

    def test_known_exponential_peak_and_volume(self):
        case = hydrology_case('pulse', [10], [10], dt=1, area=1, ia=0, loss=0, n=1, k=1)
        self.assertTrue(case['passed'])
        self.assertAlmostEqual(case['reference_peak_m3s'], 10/3.6*(1-math.exp(-1)))
        self.assertEqual(case['ideal_volume_m3'], 10000)

    def test_wrong_net_rainfall_oracle_causes_failure(self):
        # The evaluator must fail if a supposedly independent answer is wrong.
        case = hydrology_case('negative_control', [10], [5], dt=1, area=1, ia=0, loss=0, n=1, k=1)
        self.assertFalse(case['passed'])

    def test_zero_reference_stays_finite(self):
        case = hydrology_case('zero', [0], [0], dt=.5, area=2, ia=0, loss=0, n=2.5, k=1.2)
        self.assertTrue(case['passed'])
        self.assertEqual(case['volume_relative_error'], 0)


if __name__ == '__main__':
    unittest.main()
