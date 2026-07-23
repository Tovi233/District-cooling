import unittest

import numpy as np

from district_cooling.flexibility import (
    PowerResponseSeries,
    calculate_collaboration_effect,
    calculate_flexibility_metrics,
)


class FlexibilityMetricsTest(unittest.TestCase):
    def test_calculates_formal_power_curve_metrics(self):
        series = PowerResponseSeries(
            time_h=np.array([0.0, 1.0, 2.0, 3.0, 4.0]),
            p_base_kw=np.array([100.0, 100.0, 100.0, 100.0, 100.0]),
            p_response_kw=np.array([100.0, 60.0, 50.0, 100.0, 100.0]),
            p_rebound_kw=np.array([100.0, 100.0, 100.0, 130.0, 110.0]),
            response_start_h=1.0,
            response_end_h=2.0,
            rebound_end_h=4.0,
        )

        metrics = calculate_flexibility_metrics(series)

        self.assertAlmostEqual(metrics.max_reduction_power_kw, 50.0)
        self.assertAlmostEqual(metrics.time_to_max_reduction_h, 1.0)
        self.assertAlmostEqual(metrics.average_reduction_power_kw, 45.0)
        self.assertAlmostEqual(metrics.max_rebound_power_kw, 30.0)
        self.assertAlmostEqual(metrics.rebound_duration_h, 2.0)
        self.assertAlmostEqual(metrics.average_rebound_power_kw, 17.5)
        self.assertAlmostEqual(metrics.comprehensive_flexibility_kw, 20.0)

    def test_calculates_collaboration_effect(self):
        result = calculate_collaboration_effect(single_value=100.0, joint_value=125.0)

        self.assertAlmostEqual(result.absolute_delta, 25.0)
        self.assertAlmostEqual(result.relative_delta_percent, 25.0)


if __name__ == "__main__":
    unittest.main()
