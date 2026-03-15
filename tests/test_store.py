from __future__ import annotations

from custom_components.iris.store import IrisRuntimeStore

from .common import build_bootstrap, build_catalog, build_dashboard, build_state_snapshot


def test_runtime_store_detects_projection_gap_and_requests_full_resync() -> None:
    store = IrisRuntimeStore()
    store.apply_bootstrap(build_bootstrap())
    store.apply_catalog(build_catalog())
    store.apply_dashboard(build_dashboard())
    store.apply_state_snapshot(build_state_snapshot())

    actions = store.apply_websocket_message(
        {
            "type": "collection_patch",
            "projection_epoch": "20260315T000000Z-stage3",
            "sequence": 8,
            "collection_key": "assets.snapshot",
            "op": "upsert",
            "path": "ETHUSD",
            "value": {"market_regime": "distribution"},
        }
    )

    assert actions == {"full_resync"}
    assert store.last_error == "projection_gap"


def test_runtime_store_applies_resync_required_control_message() -> None:
    store = IrisRuntimeStore()
    store.apply_state_snapshot(build_state_snapshot())

    actions = store.apply_websocket_message(
        {
            "type": "resync_required",
            "reason": "queue_overflow",
            "state_url": "/api/v1/ha/state",
        }
    )

    assert actions == {"full_resync"}
    assert store.last_error == "queue_overflow"
