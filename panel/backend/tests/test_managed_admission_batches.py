"""Contracts for atomic multi-profile managed admission."""

import unittest

from pydantic import ValidationError

from src.modules.network.managed_runtime.domain.admissions import (
    ManagedAdmissionBatchCreate,
    ManagedAdmissionBatchItemCreate,
    ManagedAdmissionReceipt,
    ManagedAdmissionSubmission,
)


def admission_submission(
    window_id: str, claim_token: str = "c" * 32
) -> ManagedAdmissionSubmission:
    return ManagedAdmissionSubmission(
        claim_token=claim_token,
        original_receipt="{}",
        receipt=ManagedAdmissionReceipt(
            epoch="a" * 32,
            window_id=window_id,
            receipt_sha256="d" * 64,
            bytes=2,
        ),
    )


class ManagedAdmissionBatchContractTest(unittest.TestCase):
    def test_batch_maps_submissions_to_unique_window_identities(self):
        first = ManagedAdmissionBatchItemCreate(
            window_id="b" * 32,
            submission=admission_submission("b" * 32),
        )
        second = ManagedAdmissionBatchItemCreate(
            window_id="e" * 32,
            submission=admission_submission("e" * 32, "f" * 32),
        )

        batch = ManagedAdmissionBatchCreate(
            batch_request_key="admission_batch_0001",
            windows=[first, second],
        )

        self.assertEqual(
            [item.window_id for item in batch.windows],
            ["b" * 32, "e" * 32],
        )

    def test_batch_rejects_duplicate_window_and_claim_task(self):
        item = ManagedAdmissionBatchItemCreate(
            window_id="b" * 32,
            submission=admission_submission("b" * 32),
        )

        with self.assertRaises(ValidationError):
            ManagedAdmissionBatchCreate(
                batch_request_key="admission_batch_0001",
                windows=[item, item],
            )

        other = ManagedAdmissionBatchItemCreate(
            window_id="e" * 32,
            submission=admission_submission("e" * 32),
        )
        with self.assertRaises(ValidationError):
            ManagedAdmissionBatchCreate(
                batch_request_key="admission_batch_0002",
                windows=[item, other],
            )

    def test_batch_rejects_receipt_bound_to_another_window(self):
        with self.assertRaises(ValidationError):
            ManagedAdmissionBatchItemCreate(
                window_id="b" * 32,
                submission=admission_submission("e" * 32),
            )


if __name__ == "__main__":
    unittest.main()
