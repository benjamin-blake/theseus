"""Mirror-home guard: scripts/s3_log_store.py exposes no ops-table routing surface.

PLAN-t2-26-retire-ops-session-log: the ops-table routing concept (_OPS_TABLE_ROUTING,
FALLBACK_OPS_TABLE_ROUTING, get_ops_table_routing()) was retired alongside the
ops_session_log table it existed to route. This module keeps only the
priority_queue_key accessor.
"""

from __future__ import annotations

import scripts.s3_log_store as store_mod


def test_no_ops_table_routing_symbols() -> None:
    """The module defines no ops-table routing constant or accessor."""
    assert not hasattr(store_mod, "_OPS_TABLE_ROUTING")
    assert not hasattr(store_mod, "FALLBACK_OPS_TABLE_ROUTING")
    assert not hasattr(store_mod, "get_ops_table_routing")


def test_registry_serves_priority_queue_key_only() -> None:
    """_load_log_storage_registry's cached dict carries only priority_queue_key."""
    store_mod._LOG_STORAGE_REGISTRY = None
    result = store_mod._load_log_storage_registry()
    assert set(result.keys()) == {"priority_queue_key"}
    assert result["priority_queue_key"] == store_mod.get_priority_queue_key()


def test_registry_fallback_on_load_error(monkeypatch) -> None:
    """A load failure falls back to FALLBACK_PRIORITY_QUEUE_KEY, not an ops-table routing fallback."""
    store_mod._LOG_STORAGE_REGISTRY = None
    monkeypatch.setattr(store_mod, "_LOG_STORAGE_CONTRACT_PATH", store_mod._REPO_ROOT / "does-not-exist.yaml")
    result = store_mod._load_log_storage_registry()
    assert result == {"priority_queue_key": store_mod.FALLBACK_PRIORITY_QUEUE_KEY}
    store_mod._LOG_STORAGE_REGISTRY = None
