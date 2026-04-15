"""Unit tests for ephemeral_warehouses.py."""

from unittest.mock import MagicMock, call, patch

import pytest

import ephemeral_warehouses
from databricks.sdk.service.sql import (
    CreateWarehouseRequestWarehouseType,
    EndpointTagPair,
    EndpointTags,
    State,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_warehouse(
    warehouse_id="wh-123",
    name="delta-router-ephemeral-99",
    state=State.RUNNING,
    tagged=True,
):
    """Build a mock warehouse object."""
    wh = MagicMock()
    wh.id = warehouse_id
    wh.name = name
    wh.state = state
    if tagged:
        wh.tags = EndpointTags(
            custom_tags=[
                EndpointTagPair(key="delta-router-managed", value="true"),
            ]
        )
    else:
        wh.tags = None
    return wh


def _make_ws():
    """Build a mock WorkspaceClient."""
    return MagicMock()


# ---------------------------------------------------------------------------
# create_for_benchmark
# ---------------------------------------------------------------------------


class TestCreateForBenchmark:
    def test_calls_sdk_correctly(self):
        ws = _make_ws()
        wait_obj = MagicMock()
        wait_obj.response.id = "wh-abc"
        ws.warehouses.create.return_value = wait_obj

        result = ephemeral_warehouses.create_for_benchmark(ws, "X-Small", 42)

        assert result == "wh-abc"
        ws.warehouses.create.assert_called_once()
        kwargs = ws.warehouses.create.call_args.kwargs
        assert kwargs["name"] == "delta-router-ephemeral-42"
        assert kwargs["cluster_size"] == "X-Small"
        assert kwargs["warehouse_type"] == CreateWarehouseRequestWarehouseType.PRO
        assert kwargs["auto_stop_mins"] == 5
        assert kwargs["enable_serverless_compute"] is True

    def test_returns_warehouse_id(self):
        ws = _make_ws()
        wait_obj = MagicMock()
        wait_obj.response.id = "wh-xyz-789"
        ws.warehouses.create.return_value = wait_obj

        assert ephemeral_warehouses.create_for_benchmark(ws, "Small", 1) == "wh-xyz-789"

    def test_tags_include_managed_marker(self):
        ws = _make_ws()
        wait_obj = MagicMock()
        wait_obj.response.id = "wh-1"
        ws.warehouses.create.return_value = wait_obj

        ephemeral_warehouses.create_for_benchmark(ws, "2X-Small", 7)

        tags_arg = ws.warehouses.create.call_args.kwargs["tags"]
        assert isinstance(tags_arg, EndpointTags)
        assert len(tags_arg.custom_tags) == 1
        tag = tags_arg.custom_tags[0]
        assert tag.key == "delta-router-managed"
        assert tag.value == "true"


# ---------------------------------------------------------------------------
# wait_for_running
# ---------------------------------------------------------------------------


class TestWaitForRunning:
    @patch("ephemeral_warehouses.time")
    def test_returns_true_on_running(self, mock_time):
        mock_time.monotonic.side_effect = [0.0, 0.0]  # start, check
        ws = _make_ws()
        ws.warehouses.get.return_value = _make_warehouse(state=State.RUNNING)

        assert ephemeral_warehouses.wait_for_running(ws, "wh-1", timeout_s=60) is True

    @patch("ephemeral_warehouses.time")
    def test_polls_until_running(self, mock_time):
        # Time progression: start=0, check=0, sleep, check=1, sleep, check=2
        mock_time.monotonic.side_effect = [0.0, 0.0, 1.0, 3.0]

        ws = _make_ws()
        ws.warehouses.get.side_effect = [
            _make_warehouse(state=State.STARTING),
            _make_warehouse(state=State.STARTING),
            _make_warehouse(state=State.RUNNING),
        ]

        assert ephemeral_warehouses.wait_for_running(ws, "wh-1", timeout_s=60) is True
        assert ws.warehouses.get.call_count == 3
        assert mock_time.sleep.call_count == 2

    @patch("ephemeral_warehouses.time")
    def test_returns_false_on_timeout(self, mock_time):
        # Each monotonic call returns increasing time past the deadline
        call_count = 0

        def advancing_time():
            nonlocal call_count
            call_count += 1
            # First call is for deadline calc (returns 0), second checks (0 < 5 -> True),
            # then we keep returning STARTING, third check exceeds deadline
            return [0.0, 0.0, 3.0, 6.0][min(call_count - 1, 3)]

        mock_time.monotonic.side_effect = advancing_time

        ws = _make_ws()
        ws.warehouses.get.return_value = _make_warehouse(state=State.STARTING)

        assert ephemeral_warehouses.wait_for_running(ws, "wh-1", timeout_s=5) is False

    @patch("ephemeral_warehouses.time")
    def test_returns_false_on_deleted(self, mock_time):
        mock_time.monotonic.side_effect = [0.0, 0.0]
        ws = _make_ws()
        ws.warehouses.get.return_value = _make_warehouse(state=State.DELETED)

        assert ephemeral_warehouses.wait_for_running(ws, "wh-1", timeout_s=60) is False

    @patch("ephemeral_warehouses.time")
    def test_returns_false_on_deleting(self, mock_time):
        mock_time.monotonic.side_effect = [0.0, 0.0]
        ws = _make_ws()
        ws.warehouses.get.return_value = _make_warehouse(state=State.DELETING)

        assert ephemeral_warehouses.wait_for_running(ws, "wh-1", timeout_s=60) is False

    @patch("ephemeral_warehouses.time")
    def test_backoff_increases(self, mock_time):
        # Let it poll 3 times then timeout
        mock_time.monotonic.side_effect = [0.0, 0.0, 2.0, 5.0, 100.0]

        ws = _make_ws()
        ws.warehouses.get.return_value = _make_warehouse(state=State.STARTING)

        ephemeral_warehouses.wait_for_running(ws, "wh-1", timeout_s=10)

        # Check that sleep intervals increase
        sleep_calls = [c.args[0] for c in mock_time.sleep.call_args_list]
        assert len(sleep_calls) >= 2
        assert sleep_calls[1] > sleep_calls[0]  # backoff is increasing


# ---------------------------------------------------------------------------
# delete_warehouse
# ---------------------------------------------------------------------------


class TestDeleteWarehouse:
    def test_deletes_tagged_warehouse(self):
        ws = _make_ws()
        ws.warehouses.get.return_value = _make_warehouse(tagged=True)

        ephemeral_warehouses.delete_warehouse(ws, "wh-123")

        ws.warehouses.delete.assert_called_once_with("wh-123")

    def test_refuses_to_delete_untagged_warehouse(self):
        ws = _make_ws()
        ws.warehouses.get.return_value = _make_warehouse(tagged=False)

        ephemeral_warehouses.delete_warehouse(ws, "wh-123")

        ws.warehouses.delete.assert_not_called()

    def test_logs_warning_on_failure(self):
        ws = _make_ws()
        ws.warehouses.get.return_value = _make_warehouse(tagged=True)
        ws.warehouses.delete.side_effect = RuntimeError("API error")

        # Should not raise
        ephemeral_warehouses.delete_warehouse(ws, "wh-123")

    def test_logs_warning_when_get_fails(self):
        ws = _make_ws()
        ws.warehouses.get.side_effect = RuntimeError("Not found")

        # Should not raise
        ephemeral_warehouses.delete_warehouse(ws, "wh-123")
        ws.warehouses.delete.assert_not_called()


# ---------------------------------------------------------------------------
# cleanup_orphans
# ---------------------------------------------------------------------------


class TestCleanupOrphans:
    def test_filters_by_name_and_tag(self):
        ws = _make_ws()
        orphan = _make_warehouse(
            warehouse_id="wh-orphan",
            name="delta-router-ephemeral-55",
            tagged=True,
        )
        user_wh = _make_warehouse(
            warehouse_id="wh-user",
            name="my-production-warehouse",
            tagged=False,
        )
        wrong_name = _make_warehouse(
            warehouse_id="wh-other",
            name="other-ephemeral-thing",
            tagged=True,
        )
        # Name matches but no tag
        no_tag = _make_warehouse(
            warehouse_id="wh-notag",
            name="delta-router-ephemeral-77",
            tagged=False,
        )
        ws.warehouses.list.return_value = [orphan, user_wh, wrong_name, no_tag]
        # get() called during delete_warehouse for tag verification
        ws.warehouses.get.return_value = orphan

        count = ephemeral_warehouses.cleanup_orphans(ws)

        assert count == 1
        ws.warehouses.delete.assert_called_once_with("wh-orphan")

    def test_returns_count(self):
        ws = _make_ws()
        o1 = _make_warehouse(
            warehouse_id="wh-1", name="delta-router-ephemeral-10", tagged=True
        )
        o2 = _make_warehouse(
            warehouse_id="wh-2", name="delta-router-ephemeral-20", tagged=True
        )
        ws.warehouses.list.return_value = [o1, o2]
        # get() returns tagged warehouses for both
        ws.warehouses.get.side_effect = [
            _make_warehouse(warehouse_id="wh-1", tagged=True),
            _make_warehouse(warehouse_id="wh-2", tagged=True),
        ]

        assert ephemeral_warehouses.cleanup_orphans(ws) == 2

    def test_no_orphans_returns_zero(self):
        ws = _make_ws()
        ws.warehouses.list.return_value = [
            _make_warehouse(warehouse_id="wh-1", name="my-warehouse", tagged=False),
        ]

        assert ephemeral_warehouses.cleanup_orphans(ws) == 0
        ws.warehouses.delete.assert_not_called()

    def test_empty_list_returns_zero(self):
        ws = _make_ws()
        ws.warehouses.list.return_value = []

        assert ephemeral_warehouses.cleanup_orphans(ws) == 0

    def test_handles_list_failure(self):
        ws = _make_ws()
        ws.warehouses.list.side_effect = RuntimeError("API down")

        # Should not raise
        count = ephemeral_warehouses.cleanup_orphans(ws)
        assert count == 0


# ---------------------------------------------------------------------------
# _has_managed_tag helper
# ---------------------------------------------------------------------------


class TestHasManagedTag:
    def test_true_with_correct_tag(self):
        wh = _make_warehouse(tagged=True)
        assert ephemeral_warehouses._has_managed_tag(wh) is True

    def test_false_without_tags(self):
        wh = _make_warehouse(tagged=False)
        assert ephemeral_warehouses._has_managed_tag(wh) is False

    def test_false_with_wrong_tag_key(self):
        wh = MagicMock()
        wh.tags = EndpointTags(
            custom_tags=[EndpointTagPair(key="other-key", value="true")]
        )
        assert ephemeral_warehouses._has_managed_tag(wh) is False

    def test_false_with_wrong_tag_value(self):
        wh = MagicMock()
        wh.tags = EndpointTags(
            custom_tags=[EndpointTagPair(key="delta-router-managed", value="false")]
        )
        assert ephemeral_warehouses._has_managed_tag(wh) is False

    def test_false_with_empty_custom_tags(self):
        wh = MagicMock()
        wh.tags = EndpointTags(custom_tags=[])
        assert ephemeral_warehouses._has_managed_tag(wh) is False
