from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from papilio_proxy.modules.accounts.users.app.services import UserAccessService
from papilio_proxy.modules.accounts.users.domain.entities import UnknownUserError
from papilio_proxy.modules.network.nodes.app.identity import node_email


class UserAccessTests(IsolatedAsyncioTestCase):
    async def test_block_commits_policy_before_revoking_all_configurations(self) -> None:
        repository, node = AsyncMock(), AsyncMock()
        events: list[str] = []

        async def persist(*args: object) -> list[str]:
            events.append("committed")
            return ["order-one", "order-two"]

        async def revoke(email: str) -> None:
            self.assertEqual(events[0], "committed")
            events.append(email)

        repository.set_blocked.side_effect = persist
        node.remove.side_effect = revoke
        result = await UserAccessService(repository, node).set_blocked(77, True, " abuse ", "admin")
        repository.set_blocked.assert_awaited_once_with(77, True, "abuse", "admin")
        self.assertEqual(events[1:], [node_email("order-one"), node_email("order-two")])
        self.assertTrue(result.is_blocked)
        self.assertFalse(result.enforcement_pending)

    async def test_node_failure_leaves_durable_block_and_reports_pending(self) -> None:
        repository, node = AsyncMock(), AsyncMock()
        repository.set_blocked.return_value = ["first", "second"]
        node.remove.side_effect = [RuntimeError("unavailable"), None]
        result = await UserAccessService(repository, node).set_blocked(77, True, "", "admin")
        self.assertTrue(result.enforcement_pending)
        self.assertEqual(node.remove.await_count, 2)
        repository.set_blocked.assert_awaited_once()

    async def test_missing_node_reports_pending_only_for_existing_configurations(self) -> None:
        repository = AsyncMock()
        repository.set_blocked.return_value = ["existing"]
        service = UserAccessService(repository)
        self.assertTrue((await service.set_blocked(77, True, "", "admin")).enforcement_pending)
        repository.set_blocked.return_value = []
        self.assertFalse((await service.set_blocked(77, True, "", "admin")).enforcement_pending)

    async def test_unblock_only_changes_policy_without_recreating_or_resetting_access(self) -> None:
        repository, node = AsyncMock(), AsyncMock()
        repository.set_blocked.return_value = ["existing"]
        result = await UserAccessService(repository, node).set_blocked(77, False, "", "admin")
        self.assertFalse(result.is_blocked)
        node.remove.assert_not_awaited()
        node.ensure.assert_not_awaited()

    async def test_unknown_user_does_not_touch_node(self) -> None:
        repository, node = AsyncMock(), AsyncMock()
        repository.set_blocked.side_effect = UnknownUserError("not found")
        with self.assertRaises(UnknownUserError):
            await UserAccessService(repository, node).set_blocked(77, True, "", "admin")
        node.remove.assert_not_awaited()

    async def test_invalid_identifier_or_reason_does_not_write(self) -> None:
        repository = AsyncMock()
        service = UserAccessService(repository)
        for identifier, reason in ((0, ""), (-1, ""), (2**63, ""), (77, "x" * 301)):
            with self.assertRaises(ValueError):
                await service.set_blocked(identifier, True, reason, "admin")
        repository.set_blocked.assert_not_awaited()
