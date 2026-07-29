import sys
import unittest
from unittest.mock import MagicMock, patch

from app.database.models import SubscriptionPlan
from app.bootstrap.adapters import zotero_workflow as zotero_import_module
from app.bootstrap.adapters.zotero_workflow import (
    _compute_max_new_imports,
)


class TestComputeMaxNewImports(unittest.TestCase):
    """Tests for _compute_max_new_imports and get_remaining_paper_upload_slots."""

    def _make_user(self):
        user = MagicMock()
        user.id = "user-1"
        return user

    @patch.object(zotero_import_module, "get_remaining_paper_upload_slots")
    @patch.object(zotero_import_module, "can_user_upload_paper")
    def test_basic_plan_5_papers_remaining(self, mock_can, mock_remaining):
        """Basic user with 5 papers already → 5 slots remaining out of 10 limit."""
        mock_can.return_value = (True, None)
        mock_remaining.return_value = 5

        result, err = _compute_max_new_imports(MagicMock(), self._make_user(), limit=50)

        self.assertEqual(result, 5)
        self.assertIsNone(err)

    @patch.object(zotero_import_module, "get_remaining_paper_upload_slots")
    @patch.object(zotero_import_module, "can_user_upload_paper")
    def test_basic_plan_at_limit(self, mock_can, mock_remaining):
        """Basic user with 10 papers → blocked, 0 slots."""
        mock_can.return_value = (
            False,
            "You have reached your paper upload limit (10 papers)",
        )
        mock_remaining.return_value = 0

        result, err = _compute_max_new_imports(MagicMock(), self._make_user(), limit=50)

        self.assertEqual(result, 0)
        self.assertIsNotNone(err)
        mock_remaining.assert_not_called()

    @patch.object(zotero_import_module, "get_remaining_paper_upload_slots")
    @patch.object(zotero_import_module, "can_user_upload_paper")
    def test_researcher_plan_1_slot_remaining(self, mock_can, mock_remaining):
        """Researcher with 499 papers → 1 slot, even if limit=50."""
        mock_can.return_value = (True, None)
        mock_remaining.return_value = 1

        result, err = _compute_max_new_imports(MagicMock(), self._make_user(), limit=50)

        self.assertEqual(result, 1)
        self.assertIsNone(err)

    @patch.object(zotero_import_module, "get_remaining_paper_upload_slots")
    @patch.object(zotero_import_module, "can_user_upload_paper")
    def test_request_limit_caps_slots(self, mock_can, mock_remaining):
        """When remaining (10) > request limit (3), request limit wins."""
        mock_can.return_value = (True, None)
        mock_remaining.return_value = 10

        result, err = _compute_max_new_imports(MagicMock(), self._make_user(), limit=3)

        self.assertEqual(result, 3)
        self.assertIsNone(err)

    @patch.object(zotero_import_module, "get_remaining_paper_upload_slots")
    @patch.object(zotero_import_module, "can_user_upload_paper")
    def test_unlimited_plan(self, mock_can, mock_remaining):
        """Unlimited plan returns sys.maxsize; min with limit gives limit."""
        mock_can.return_value = (True, None)
        mock_remaining.return_value = sys.maxsize

        result, err = _compute_max_new_imports(MagicMock(), self._make_user(), limit=50)

        self.assertEqual(result, 50)
        self.assertIsNone(err)


class TestGetRemainingPaperUploadSlots(unittest.TestCase):
    """Tests for get_remaining_paper_upload_slots directly."""

    def _make_user(self):
        user = MagicMock()
        user.id = "user-1"
        return user

    @patch("app.modules.billing.infrastructure.quotas.resource_usage_repository")
    @patch("app.modules.billing.infrastructure.quotas.get_user_subscription_plan")
    def test_basic_5_used(self, mock_plan, mock_resource_usage):
        from app.modules.billing.infrastructure.quotas import (
            get_remaining_paper_upload_slots,
        )

        mock_plan.return_value = SubscriptionPlan.BASIC
        mock_resource_usage.completed_reference_count.return_value = 5

        result = get_remaining_paper_upload_slots(MagicMock(), self._make_user())

        self.assertEqual(result, 5)

    @patch("app.modules.billing.infrastructure.quotas.resource_usage_repository")
    @patch("app.modules.billing.infrastructure.quotas.get_user_subscription_plan")
    def test_basic_at_limit(self, mock_plan, mock_resource_usage):
        from app.modules.billing.infrastructure.quotas import (
            get_remaining_paper_upload_slots,
        )

        mock_plan.return_value = SubscriptionPlan.BASIC
        mock_resource_usage.completed_reference_count.return_value = 10

        result = get_remaining_paper_upload_slots(MagicMock(), self._make_user())

        self.assertEqual(result, 0)

    @patch("app.modules.billing.infrastructure.quotas.resource_usage_repository")
    @patch("app.modules.billing.infrastructure.quotas.get_user_subscription_plan")
    def test_researcher_499(self, mock_plan, mock_resource_usage):
        from app.modules.billing.infrastructure.quotas import (
            get_remaining_paper_upload_slots,
        )

        mock_plan.return_value = SubscriptionPlan.RESEARCHER
        mock_resource_usage.completed_reference_count.return_value = 499

        result = get_remaining_paper_upload_slots(MagicMock(), self._make_user())

        self.assertEqual(result, 1)

    @patch("app.modules.billing.infrastructure.quotas.resource_usage_repository")
    @patch("app.modules.billing.infrastructure.quotas.get_user_subscription_plan")
    def test_researcher_at_limit(self, mock_plan, mock_resource_usage):
        from app.modules.billing.infrastructure.quotas import (
            get_remaining_paper_upload_slots,
        )

        mock_plan.return_value = SubscriptionPlan.RESEARCHER
        mock_resource_usage.completed_reference_count.return_value = 500

        result = get_remaining_paper_upload_slots(MagicMock(), self._make_user())

        self.assertEqual(result, 0)

    @patch("app.modules.billing.infrastructure.quotas.resource_usage_repository")
    @patch("app.modules.billing.infrastructure.quotas.get_user_subscription_plan")
    def test_over_limit_clamps_to_zero(self, mock_plan, mock_resource_usage):
        """If somehow over limit, return 0 not negative."""
        from app.modules.billing.infrastructure.quotas import (
            get_remaining_paper_upload_slots,
        )

        mock_plan.return_value = SubscriptionPlan.BASIC
        mock_resource_usage.completed_reference_count.return_value = 15

        result = get_remaining_paper_upload_slots(MagicMock(), self._make_user())

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
