"""Tests for lecture_auto/tasks/progress.py — Redis pub/sub progress publisher."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from lecture_auto.tasks.progress import (
    get_last_progress,
    publish_progress,
    reset_redis_client,
)


@pytest.fixture(autouse=True)
def _reset_client():
    """Ensure each test starts with a fresh Redis client."""
    reset_redis_client()
    yield
    reset_redis_client()


class TestPublishProgress:
    """publish_progress writes to Redis pub/sub and persists last event."""

    @patch("lecture_auto.tasks.progress.redis_lib.Redis.from_url")
    def test_publishes_to_correct_channel(self, mock_from_url):
        mock_redis = MagicMock()
        mock_from_url.return_value = mock_redis

        publish_progress("job-abc", "vlm", 3, 10, "processing")

        # Check publish call
        mock_redis.publish.assert_called_once()
        channel, payload = mock_redis.publish.call_args[0]
        assert channel == "job:job-abc:progress"
        data = json.loads(payload)
        assert data["job_id"] == "job-abc"
        assert data["stage"] == "vlm"
        assert data["current"] == 3
        assert data["total"] == 10
        assert data["percent"] == 30.0
        assert data["status"] == "processing"

    @patch("lecture_auto.tasks.progress.redis_lib.Redis.from_url")
    def test_persists_last_progress(self, mock_from_url):
        mock_redis = MagicMock()
        mock_from_url.return_value = mock_redis

        publish_progress("job-abc", "vlm", 5, 10, "done")

        mock_redis.set.assert_called_once()
        key = mock_redis.set.call_args[0][0]
        assert key == "job:job-abc:last_progress"
        # Check TTL
        assert mock_redis.set.call_args[1]["ex"] == 86400

    @patch("lecture_auto.tasks.progress.redis_lib.Redis.from_url")
    def test_percent_zero_when_total_zero(self, mock_from_url):
        mock_redis = MagicMock()
        mock_from_url.return_value = mock_redis

        publish_progress("job-abc", "vlm", 0, 0, "processing")

        payload = mock_redis.publish.call_args[0][1]
        data = json.loads(payload)
        assert data["percent"] == 0


class TestGetLastProgress:
    """get_last_progress retrieves persisted last event."""

    @patch("lecture_auto.tasks.progress.redis_lib.Redis.from_url")
    def test_returns_parsed_json(self, mock_from_url):
        mock_redis = MagicMock()
        mock_from_url.return_value = mock_redis

        event = {"job_id": "job-xyz", "stage": "vlm", "current": 2, "total": 5, "percent": 40.0, "status": "done"}
        mock_redis.get.return_value = json.dumps(event).encode()

        result = get_last_progress("job-xyz")

        assert result == event
        mock_redis.get.assert_called_once_with("job:job-xyz:last_progress")

    @patch("lecture_auto.tasks.progress.redis_lib.Redis.from_url")
    def test_returns_none_when_no_key(self, mock_from_url):
        mock_redis = MagicMock()
        mock_from_url.return_value = mock_redis
        mock_redis.get.return_value = None

        result = get_last_progress("nonexistent")

        assert result is None


class TestResetRedisClient:
    """reset_redis_client clears the cached client."""

    @patch("lecture_auto.tasks.progress.redis_lib.Redis.from_url")
    def test_reset_forces_new_connection(self, mock_from_url):
        mock_redis = MagicMock()
        mock_from_url.return_value = mock_redis

        # First call creates connection
        publish_progress("j1", "vlm", 1, 1, "done")
        assert mock_from_url.call_count == 1

        # Reset + second call should create a new connection
        reset_redis_client()
        publish_progress("j2", "vlm", 1, 1, "done")
        assert mock_from_url.call_count == 2
