"""Canonical Draw contract regressions; these fixtures are not network evidence."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'SSQ'))

from glp.domain import Draw


def canonical_draw() -> dict:
    return {
        'issue': '2026113',
        'draw_date': '2026-09-29',
        'front': [3, 4, 20, 24, 29, 30],
        'back': [11],
    }


class DrawValidationTests(unittest.TestCase):
    def test_valid_canonical_record_roundtrips_without_coercion(self):
        value = canonical_draw()
        draw = Draw.from_dict(value)
        self.assertEqual(draw.to_dict(), value)
        self.assertIsInstance(draw.front, tuple)
        self.assertIsInstance(draw.back, tuple)

    def test_valid_leap_day_is_accepted(self):
        value = canonical_draw()
        value.update(issue='2024001', draw_date='2024-02-29')
        self.assertEqual(Draw.from_dict(value).draw_date, '2024-02-29')

    def test_issue_and_date_year_must_agree(self):
        value = canonical_draw()
        value['draw_date'] = '2025-09-29'
        with self.assertRaises(ValueError):
            Draw.from_dict(value)

    def test_non_integer_balls_are_not_coerced(self):
        for field in ('front', 'back'):
            for invalid in (True, False, 3.0, 3.9, '03', None, {}, []):
                with self.subTest(field=field, invalid=invalid):
                    value = canonical_draw()
                    value[field][0] = invalid
                    with self.assertRaises(ValueError):
                        Draw.from_dict(value)

    def test_direct_draw_validation_rejects_bool_and_float_balls(self):
        for invalid in (True, 1.0, '1', None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    Draw('2026001', '2026-01-01', (invalid, 2, 3, 4, 5, 6), (1,)).validate()
                with self.assertRaises(ValueError):
                    Draw('2026001', '2026-01-01', (1, 2, 3, 4, 5, 6), (invalid,)).validate()

    def test_invalid_calendar_and_noncanonical_dates_are_rejected(self):
        for invalid in ('2026-02-29', '2026-04-31', '2026-13-01', '2026-00-01',
                        '20260929', '2026-W40-2', '2026-9-29', '2026/09/29',
                        '2026-09-29T00:00:00Z', '2026-09-29 ', '', None,
                        date(2026, 9, 29), 20260929):
            with self.subTest(invalid=invalid):
                value = canonical_draw()
                value['draw_date'] = invalid
                with self.assertRaises(ValueError):
                    Draw.from_dict(value)

    def test_issue_requires_ascii_canonical_string(self):
        for invalid in (2026113, 2026113.0, True, None, '202611', '20261130',
                        '2026abc', '2026\u0661\u0661\u0663', '2026113 ', '1999113'):
            with self.subTest(invalid=invalid):
                value = canonical_draw()
                value['issue'] = invalid
                with self.assertRaises(ValueError):
                    Draw.from_dict(value)

    def test_malformed_record_and_ball_containers_are_rejected(self):
        for invalid in (None, [], 'record', 1):
            with self.subTest(record=invalid):
                with self.assertRaises(ValueError):
                    Draw.from_dict(invalid)
        for key in canonical_draw():
            value = canonical_draw()
            del value[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                Draw.from_dict(value)
        for field in ('front', 'back'):
            for invalid in ('123456', None, 11, {1: 1}):
                with self.subTest(field=field, container=invalid):
                    value = canonical_draw()
                    value[field] = invalid
                    with self.assertRaises(ValueError):
                        Draw.from_dict(value)

    def test_range_uniqueness_order_and_cardinality_remain_enforced(self):
        cases = (
            ('front', [3, 4, 20, 24, 29]),
            ('front', [3, 4, 20, 24, 29, 29]),
            ('front', [4, 3, 20, 24, 29, 30]),
            ('front', [0, 4, 20, 24, 29, 30]),
            ('front', [3, 4, 20, 24, 29, 34]),
            ('back', []), ('back', [1, 2]), ('back', [0]), ('back', [17]),
        )
        for field, invalid in cases:
            with self.subTest(field=field, invalid=invalid):
                value = canonical_draw()
                value[field] = invalid
                with self.assertRaises(ValueError):
                    Draw.from_dict(value)


if __name__ == '__main__':
    unittest.main()
