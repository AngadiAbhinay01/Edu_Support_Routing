import unittest
from datetime import datetime as D
from edu_support.bizhours import add_business_hours, business_hours_between, is_business_day, sla_due, roll_forward


class BusinessHours(unittest.TestCase):
    def test_within_day(self):
        self.assertEqual(add_business_hours(D(2026, 10, 5, 10), 2), D(2026, 10, 5, 12))      # Monday

    def test_overnight_rollover(self):
        self.assertEqual(add_business_hours(D(2026, 10, 5, 16), 2), D(2026, 10, 6, 10))

    def test_friday_evening_skips_weekend(self):
        self.assertEqual(add_business_hours(D(2026, 10, 9, 16, 30), 1), D(2026, 10, 12, 9, 30))

    def test_created_on_saturday_starts_monday(self):
        self.assertEqual(add_business_hours(D(2026, 10, 10, 11), 1), D(2026, 10, 12, 10))

    def test_before_opening(self):
        self.assertEqual(roll_forward(D(2026, 10, 6, 7)), D(2026, 10, 6, 9))

    def test_exactly_at_close(self):
        self.assertEqual(roll_forward(D(2026, 10, 6, 17)), D(2026, 10, 7, 9))

    def test_zero_hours(self):
        self.assertEqual(add_business_hours(D(2026, 10, 6, 10), 0), D(2026, 10, 6, 10))

    def test_between_is_inverse_of_add(self):
        a = D(2026, 10, 7, 15)
        self.assertAlmostEqual(business_hours_between(a, add_business_hours(a, 20)), 20, places=2)

    def test_between_ignores_weekend(self):
        self.assertAlmostEqual(business_hours_between(D(2026, 10, 9, 16), D(2026, 10, 12, 10)), 2, places=2)

    def test_calendar_mode_differs(self):
        s = D(2026, 10, 9, 16)
        self.assertNotEqual(sla_due(s, 8, "business"), sla_due(s, 8, "calendar"))

    def test_weekend_not_business_day(self):
        self.assertFalse(is_business_day(D(2026, 10, 10).date()))


if __name__ == "__main__":
    unittest.main()
