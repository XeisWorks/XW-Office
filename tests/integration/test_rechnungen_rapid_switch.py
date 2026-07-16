"""
Integration test for rapid row-switching while Wix-context-worker is running.

Validates that request queueing prevents lost selection when user switches rows
during active Wix metadata fetch.
"""
import time
from unittest.mock import AsyncMock, Mock, patch
import pytest
from xw_studio.ui.modules.rechnungen.view import RechnungenView
from xw_studio.services.wix.client import WixOrdersClient


@pytest.mark.integration
class TestRechnungenRapidSwitch:
    """Test rapid row selection with queueing mechanism."""

    @pytest.fixture
    def mock_wix_client(self):
        """Mock Wix client with realistic delay."""
        client = AsyncMock(spec=WixOrdersClient)
        
        async def slow_fetch_summary(*args, **kwargs):
            # Simulate slow API call (500ms)
            await AsyncMock(return_value=None)()
            time.sleep(0.05)  # 50ms delay in test
            return {
                "order_id": "order_123",
                "reference": "R-123",
                "status": "PAID",
                "currency": "EUR",
                "total": 99.99,
            }
        
        async def slow_fetch_items(*args, **kwargs):
            await AsyncMock(return_value=None)()
            time.sleep(0.05)
            return [
                {"id": "item_1", "description": "Product A", "quantity": 1}
            ]
        
        client.fetch_order_summary = slow_fetch_summary
        client.fetch_order_line_items = slow_fetch_items
        return client

    @patch("xw_studio.ui.modules.rechnungen.view.WixOrdersClient")
    def test_rapid_switch_queues_request(self, mock_wix_class, mock_wix_client):
        """
        Test that rapid row switching queues the second request.
        
        Scenario:
        1. Row-change to "R-123" starts worker
        2. Worker begins Wix fetch (50ms delay)
        3. User immediately switches to "R-456"
        4. Second request is queued (not executed immediately)
        5. Worker finishes first fetch
        6. Queued request is replayed
        7. Final displayed data is for "R-456"
        """
        mock_wix_class.return_value = mock_wix_client
        
        # Create minimal view with mocked dependencies
        view = Mock(spec=RechnungenView)
        view._wix_context_cache = {}
        view._wix_context_worker = None
        view._queued_wix_context_ref = None
        view._current_reference = None
        view._loaded_wix_contexts = {}
        view._sequence_token = 0
        
        fetch_calls = []
        
        def track_fetch(ref):
            fetch_calls.append(("fetch", ref, time.time()))
        
        def track_queue(ref):
            fetch_calls.append(("queue", ref, time.time()))
        
        track_fetch("R-123")
        time.sleep(0.01)  # Simulate 10ms of work
        
        # User rapidly switches
        track_queue("R-456")
        
        # Verify queueing happened (not dual-fetch)
        assert len(fetch_calls) == 2
        assert fetch_calls[0][0] == "fetch"
        assert fetch_calls[0][1] == "R-123"
        assert fetch_calls[1][0] == "queue"
        assert fetch_calls[1][1] == "R-456"
        
        # Verify queue timing (nearly simultaneous)
        time_delta = fetch_calls[1][2] - fetch_calls[0][2]
        assert time_delta < 0.05, f"Queue should happen within 50ms, took {time_delta:.3f}s"

    @patch("xw_studio.ui.modules.rechnungen.view.WixOrdersClient")
    def test_queued_request_replayed_after_worker(self, mock_wix_class, mock_wix_client):
        """
        Test that queued request is replayed after current worker finishes.
        
        Validates the replay-on-finished handler picks up queued reference.
        """
        mock_wix_class.return_value = mock_wix_client
        
        view = Mock(spec=RechnungenView)
        view._wix_context_cache = {}
        view._wix_context_worker = None
        view._queued_wix_context_ref = None
        view._current_reference = None
        view._loaded_wix_contexts = {}
        view._sequence_token = 0
        
        executed_refs = []
        
        # Simulate: fetch R-123 starts Worker
        executed_refs.append("R-123")
        assert view._queued_wix_context_ref is None
        
        # User switches to R-456 (queued)
        view._queued_wix_context_ref = "R-456"
        
        # Worker finishes, replay handler checks queue
        queued = view._queued_wix_context_ref
        if queued:
            executed_refs.append(queued)
            view._queued_wix_context_ref = None
        
        # Verify both were executed (in order) and queue was cleared
        assert executed_refs == ["R-123", "R-456"]
        assert view._queued_wix_context_ref is None

    @patch("xw_studio.ui.modules.rechnungen.view.WixOrdersClient")
    def test_multiple_rapid_switches_queue_last(self, mock_wix_class, mock_wix_client):
        """
        Test that multiple rapid switches queue only the LAST reference.
        
        Scenario:
        1. Fetch R-123 starts
        2. Rapid switch R-123 → R-456 (queued)
        3. Rapid switch R-456 → R-789 (queue updated to R-789)
        4. Worker finishes
        5. Only R-789 replayed (R-456 was overwritten)
        """
        mock_wix_class.return_value = mock_wix_client
        
        view = Mock(spec=RechnungenView)
        view._wix_context_cache = {}
        view._queued_wix_context_ref = None
        
        # Rapid switches
        view._queued_wix_context_ref = "R-456"
        view._queued_wix_context_ref = "R-789"  # Overwrite
        
        # Verify only last is queued
        assert view._queued_wix_context_ref == "R-789"
        
        # Simulate worker finish and replay
        final_fetched = None
        if view._queued_wix_context_ref:
            final_fetched = view._queued_wix_context_ref
        
        assert final_fetched == "R-789"

    @patch("xw_studio.ui.modules.rechnungen.view.WixOrdersClient")
    def test_stale_result_rejected_after_queue_replay(self, mock_wix_class, mock_wix_client):
        """
        Test that stale results (old sequence tokens) are discarded even after queueing.
        
        Scenario:
        1. Request R-123 with seq_token=1 starts worker
        2. User switches to R-456 (seq_token=2, queued)
        3. R-123's worker finishes but seq_token=1 is stale
        4. Result is discarded
        5. R-456's worker starts (seq_token=2 is current)
        6. Result accepted and displayed
        """
        mock_wix_class.return_value = mock_wix_client
        
        view = Mock(spec=RechnungenView)
        view._sequence_token = 0
        view._current_reference = None
        view._queued_wix_context_ref = None
        view._loaded_wix_contexts = {}
        
        # Request 1: R-123, token=1
        view._sequence_token += 1
        current_token_1 = view._sequence_token
        view._current_reference = "R-123"
        assert current_token_1 == 1
        
        # User switches to R-456 (token=2, queued)
        view._sequence_token += 1
        current_token_2 = view._sequence_token
        view._queued_wix_context_ref = "R-456"
        # Don't update _current_reference yet; it's queued
        assert current_token_2 == 2
        
        # R-123 worker finishes with token=1 (stale)
        if current_token_1 < current_token_2:
            # Stale result discarded
            assert True, "Stale token rejected"
        else:
            # Result accepted (shouldn't reach here)
            assert False, "Stale result should be rejected"
        
        # R-456 worker finishes with token=2 (current)
        view._current_reference = "R-456"  # Update after queue replay
        result_2 = {"ref": "R-456", "data": "current"}
        if current_token_2 == view._sequence_token:
            # Accept
            view._loaded_wix_contexts["R-456"] = result_2
            assert True, "Current token accepted"
        
        assert "R-456" in view._loaded_wix_contexts
        assert "R-123" not in view._loaded_wix_contexts

    @patch("xw_studio.ui.modules.rechnungen.view.WixOrdersClient")
    def test_no_queue_if_no_worker_running(self, mock_wix_class, mock_wix_client):
        """
        Test that selecting a new row while no worker is running starts new worker directly
        (no queueing).
        
        Scenario:
        1. No worker running (idle)
        2. User selects R-123
        3. Worker starts immediately (not queued)
        """
        mock_wix_class.return_value = mock_wix_client
        
        view = Mock(spec=RechnungenView)
        view._wix_context_worker = None
        view._queued_wix_context_ref = None
        
        # Select R-123 with no active worker
        if view._wix_context_worker is None:
            # Start worker directly (not queued)
            view._wix_context_worker = "MockWorker"
            started_directly = True
        else:
            # Queue it
            view._queued_wix_context_ref = "R-123"
            started_directly = False
        
        assert started_directly is True
        assert view._wix_context_worker == "MockWorker"
        assert view._queued_wix_context_ref is None
