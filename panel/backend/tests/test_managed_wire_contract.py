"""Pinned wire parsing only; no native authority or core claim."""

import hashlib
import json
import unittest

from src.modules.network.managed_runtime.app.wire_encoding import (
    ManagedWireEncoding,
)
from src.modules.network.managed_runtime.domain.contracts import (
    ManagedRuntimeCapacity,
)
from src.modules.network.managed_runtime.domain.wire import (
    ManagedClosedStartupReceiptWire,
    ManagedSnapshotReceiptWire,
)


class ManagedWireContractTest(unittest.TestCase):
    def setUp(self):
        self.capacity = ManagedRuntimeCapacity(
            max_manifest_bytes=65536,
            max_window_bytes=8192,
            max_snapshot_bytes=65536,
            max_profiles_per_barrier=8,
            max_windows_per_barrier=8,
            max_pending_epochs=8,
            max_retained_receipts=32,
            max_validity_ms=60000,
            operation_timeout_ms=1000,
            scan_batch_size=8,
            retry_seconds=5,
            max_attempts=3,
        )
        installation = dict.fromkeys(
            (
                "materials_sha256",
                "executable_sha256",
                "document_sha256",
                "bindings_sha256",
            ),
            "a" * 64,
        )
        binding = {
            "profile_id": 7,
            "generation": 0,
            "configuration_id": 8,
            "configuration_revision": 1,
            "counter_identity": "counter-7",
            "inbound_tag": "node-8",
        }
        window = {
            "enforcement_mode": "strict_decoded",
            "enforcement_sha256": "b" * 64,
            "grant_id": 9,
            "window_id": "c" * 32,
            "epoch": "d" * 32,
            "installation": installation,
            "binding": binding,
            "membership_sha256": "e" * 64,
            "profile_sha256": "f" * 64,
            "baseline_upload_bytes": 100,
            "baseline_download_bytes": 200,
            "allocated_bytes": 64,
            "issued_at": "2026-10-09T00:00:00.120000Z",
            "valid_until": "2026-10-09T00:00:10.120000Z",
            "predecessor": None,
        }
        self.document = {
            "installation": installation,
            "epoch": "d" * 32,
            "barrier_id": "1" * 32,
            "adapter_revision": 1,
            "source_commit": "2" * 40,
            "accounting_scope": "decoded_managed_tcp_payload_admission",
            "frozen_at": "2026-10-09T00:00:10.120000Z",
            "profiles": [
                {
                    "binding": binding,
                    "upload_bytes": 112,
                    "download_bytes": 218,
                    "unadmitted_upload_bytes": 3,
                    "unadmitted_download_bytes": 5,
                }
            ],
            "windows": [window],
            "enforcement": [
                {
                    "profile_id": 7,
                    "window_id": "c" * 32,
                    "allocated_bytes": 64,
                    "admitted_bytes": 30,
                    "closure_reason": "window_expired",
                }
            ],
        }

    def decode(self, payload=None):
        original = payload or json.dumps(self.document, indent=2).encode()
        receipt = ManagedSnapshotReceiptWire(
            epoch="d" * 32,
            barrier_id="1" * 32,
            bytes=len(original),
            snapshot_sha256=hashlib.sha256(original).hexdigest(),
        )
        return ManagedWireEncoding.original_snapshot(
            original, receipt, self.capacity
        )

    def test_original_bytes_residue_and_new_delta_survive(self):
        original = json.dumps(self.document, indent=2).encode()
        decoded = self.decode(original)
        self.assertEqual(decoded.original_bytes, original)
        self.assertEqual(
            decoded.snapshot.profiles[0].unadmitted_upload_bytes, 3
        )
        self.assertEqual(
            decoded.snapshot.profiles[0].unadmitted_download_bytes, 5
        )
        self.assertEqual(
            decoded.snapshot.enforcement[0].closure_reason, "window_expired"
        )
        delta = ManagedWireEncoding.grant_deltas(decoded.snapshot)[0]
        self.assertEqual((delta.upload_bytes, delta.download_bytes), (12, 18))
        self.assertIn(
            '"frozen_at":"2026-10-09T00:00:10.120000Z"',
            decoded.snapshot.model_dump_json(),
        )

    def test_changed_original_digest_and_duplicate_fields_rejected(self):
        decoded = self.decode()
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            ManagedWireEncoding.original_snapshot(
                decoded.original_bytes + b" ", decoded.receipt, self.capacity
            )
        original = json.dumps(self.document).encode()
        duplicate = original[:-1] + b', "epoch":"' + b"d" * 32 + b'"}'
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.decode(duplicate)

    def test_missing_strict_final_or_changed_binding_rejected(self):
        self.document["enforcement"] = []
        with self.assertRaisesRegex(ValueError, "strict evidence"):
            self.decode()

    def test_admitted_delta_must_equal_final(self):
        self.document["enforcement"][0]["admitted_bytes"] = 31
        with self.assertRaisesRegex(ValueError, "admitted-byte"):
            self.decode()

    def test_go_window_serializer_places_utc6_fields_after_predecessor(self):
        window = self.decode().snapshot.windows[0]
        encoded = ManagedWireEncoding.window_bytes(window)
        self.assertTrue(
            encoded.endswith(
                b'"issued_at":"2026-10-09T00:00:00.120000Z",'
                b'"valid_until":"2026-10-09T00:00:10.120000Z"}'
            )
        )
        self.assertLess(
            encoded.index(b'"predecessor"'), encoded.index(b'"issued_at"')
        )

    def test_metadata_snapshot_preserves_profiles_without_grant_accounting(
        self,
    ):
        self.document.pop("windows")
        self.document.pop("enforcement")
        decoded = self.decode()
        self.assertEqual(len(decoded.snapshot.profiles), 1)
        with self.assertRaisesRegex(ValueError, "requires windows"):
            ManagedWireEncoding.grant_deltas(decoded.snapshot)

    def test_duplicate_profiles_rejected_even_without_windows(self):
        self.document.pop("windows")
        self.document.pop("enforcement")
        self.document["profiles"].append(self.document["profiles"][0].copy())
        with self.assertRaisesRegex(ValueError, "profile identities"):
            self.decode()

    def test_duplicate_counters_rejected_for_distinct_profiles(self):
        self.document.pop("windows")
        self.document.pop("enforcement")
        duplicate = self.document["profiles"][0].copy()
        duplicate["binding"] = dict(duplicate["binding"], profile_id=17)
        self.document["profiles"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "counter identities"):
            self.decode()

    def test_per_grant_signed_overflow_rejected(self):
        window = self.document["windows"][0]
        window["enforcement_mode"] = "metadata_only"
        window["enforcement_sha256"] = ""
        window["baseline_upload_bytes"] = 0
        window["baseline_download_bytes"] = 0
        self.document.pop("enforcement")
        self.document["profiles"][0]["upload_bytes"] = 2**63 - 1
        self.document["profiles"][0]["download_bytes"] = 1
        decoded = self.decode()
        with self.assertRaisesRegex(ValueError, "signed accounting"):
            ManagedWireEncoding.grant_deltas(decoded.snapshot)

    def closed_document(self):
        totals = self.document["profiles"][0]
        window = self.document["windows"][0]
        return {
            "state": "isolated_closed_startup_observation",
            "epoch": self.document["epoch"],
            "installation": self.document["installation"],
            "adapter_revision": 1,
            "source_commit": "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0",
            "module": "github.com/xtls/xray-core@v1.260327.0",
            "accounting_scope": "decoded_managed_tcp_payload_admission",
            "accounting_mode": "window_component",
            "enforcement_mode": "strict_decoded",
            "enforcement_sha256": "b" * 64,
            "window_policy_sha256": "c" * 64,
            "profiles": [
                {
                    "binding": totals["binding"],
                    "membership_sha256": window["membership_sha256"],
                    "profile_sha256": window["profile_sha256"],
                    "phase": "enrolled_closed",
                    "active_operations": 0,
                    "resources": 0,
                    "upload_bytes": 0,
                    "download_bytes": 0,
                    "unadmitted_upload_bytes": 0,
                    "unadmitted_download_bytes": 0,
                }
            ],
            "api_authority": False,
            "budget_enforced": False,
            "deadline_enforced": False,
            "historical_only": True,
            "observed_at": "2026-10-09T00:00:10.120000Z",
        }

    def decode_closed(self, document):
        payload = json.dumps(document, indent=2).encode()
        receipt = ManagedClosedStartupReceiptWire(
            epoch=document["epoch"],
            bytes=len(payload),
            receipt_sha256=hashlib.sha256(payload).hexdigest(),
        )
        return ManagedWireEncoding.original_closed_startup(
            payload, receipt, self.capacity
        )

    def test_closed_startup_original_observation_not_activation(self):
        document = self.closed_document()
        result = self.decode_closed(document)
        self.assertEqual(
            result.original_bytes, json.dumps(document, indent=2).encode()
        )
        self.assertTrue(result.startup.historical_only)
        self.assertFalse(result.startup.api_authority)
        self.assertFalse(result.startup.budget_enforced)

    def test_closed_startup_rejects_open_and_fake_authority(self):
        document = self.closed_document()
        document["profiles"][0]["phase"] = "open"
        with self.assertRaises(ValueError):
            self.decode_closed(document)
        document = self.closed_document()
        document["api_authority"] = True
        with self.assertRaises(ValueError):
            self.decode_closed(document)

    def test_closed_startup_empty_membership_stays_empty(self):
        document = self.closed_document()
        document["profiles"] = []
        result = self.decode_closed(document)
        self.assertEqual(result.startup.profiles, ())
        self.assertFalse(result.startup.api_authority)
