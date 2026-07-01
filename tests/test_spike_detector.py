"""Tests for alerts/spike_detector.py — Z-score and volume-surge rules."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest


def _patch_db(rows_map: dict):
    """
    Return a context-manager patch for db_session whose fetchall returns
    the appropriate value based on the SQL content (matched by keyword).
    """
    def _fetchall(sql, params=()):
        sql_lower = sql.lower()
        for keyword, rows in rows_map.items():
            if keyword in sql_lower:
                return rows
        return []

    mock_db = MagicMock()
    mock_db.fetchall.side_effect = _fetchall
    return mock_db


class TestZscoreCheck:
    def test_fires_when_z_above_threshold(self):
        from alerts.spike_detector import check_zscore

        # 7 days of low neg ratio, then a spike today
        rows = [
            {"day": f"2024-01-0{i}", "total": 10, "negative_count": 1}
            for i in range(1, 7)
        ] + [{"day": "2024-01-07", "total": 10, "negative_count": 9}]

        mock_db = _patch_db({
            "neg": rows,
            "resolved": [],  # no existing open alert
        })

        with patch("alerts.spike_detector.db_session") as ctx:
            ctx.return_value.__enter__ = lambda s: mock_db
            ctx.return_value.__exit__ = MagicMock(return_value=False)
            fired = check_zscore("PTT")

        assert fired is True

    def test_does_not_fire_below_threshold(self):
        from alerts.spike_detector import check_zscore

        rows = [
            {"day": f"2024-01-0{i}", "total": 10, "negative_count": 3}
            for i in range(1, 8)
        ]
        mock_db = _patch_db({"neg": rows, "resolved": []})

        with patch("alerts.spike_detector.db_session") as ctx:
            ctx.return_value.__enter__ = lambda s: mock_db
            ctx.return_value.__exit__ = MagicMock(return_value=False)
            fired = check_zscore("PTT")

        assert fired is False

    def test_suppresses_duplicate_open_alert(self):
        from alerts.spike_detector import check_zscore

        rows = [
            {"day": f"2024-01-0{i}", "total": 10, "negative_count": 1}
            for i in range(1, 7)
        ] + [{"day": "2024-01-07", "total": 10, "negative_count": 9}]

        # Simulate existing open alert
        mock_db = _patch_db({
            "neg": rows,
            "resolved": [{"alert_id": 1}],  # open alert exists
        })

        with patch("alerts.spike_detector.db_session") as ctx:
            ctx.return_value.__enter__ = lambda s: mock_db
            ctx.return_value.__exit__ = MagicMock(return_value=False)
            fired = check_zscore("PTT")

        assert fired is False

    def test_requires_minimum_data_points(self):
        from alerts.spike_detector import check_zscore

        # Only 2 days — not enough
        rows = [
            {"day": "2024-01-01", "total": 10, "negative_count": 9},
            {"day": "2024-01-02", "total": 10, "negative_count": 9},
        ]
        mock_db = _patch_db({"neg": rows, "resolved": []})

        with patch("alerts.spike_detector.db_session") as ctx:
            ctx.return_value.__enter__ = lambda s: mock_db
            ctx.return_value.__exit__ = MagicMock(return_value=False)
            fired = check_zscore("PTT")

        assert fired is False


class TestVolumeSurgeCheck:
    def test_fires_when_surge_above_multiplier(self):
        from alerts.spike_detector import check_volume_surge

        # today = 30 posts, 7-day avg = 5 → ratio = 6× > 3×
        today_rows = [{"cnt": 30}]
        weekly_rows = [{"day": f"2024-01-0{i}", "cnt": 5} for i in range(1, 8)]
        mock_db = _patch_db({
            "date(p.posted_at) =": today_rows,
            "between": weekly_rows,
            "resolved": [],
        })

        with patch("alerts.spike_detector.db_session") as ctx:
            ctx.return_value.__enter__ = lambda s: mock_db
            ctx.return_value.__exit__ = MagicMock(return_value=False)
            fired = check_volume_surge("KBANK")

        assert fired is True

    def test_does_not_fire_on_normal_volume(self):
        from alerts.spike_detector import check_volume_surge

        today_rows = [{"cnt": 6}]
        weekly_rows = [{"day": f"2024-01-0{i}", "cnt": 5} for i in range(1, 8)]
        mock_db = _patch_db({
            "date(p.posted_at) =": today_rows,
            "between": weekly_rows,
            "resolved": [],
        })

        with patch("alerts.spike_detector.db_session") as ctx:
            ctx.return_value.__enter__ = lambda s: mock_db
            ctx.return_value.__exit__ = MagicMock(return_value=False)
            fired = check_volume_surge("KBANK")

        assert fired is False
