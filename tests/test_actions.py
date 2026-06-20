import unittest

from codex_actions import ACTION_SPECS, action_by_id, action_groups, rank_actions


class ActionCatalogTests(unittest.TestCase):
    def test_lookup_finds_action_by_id(self) -> None:
        action = action_by_id("quality.run")
        self.assertIsNotNone(action)
        self.assertEqual(action.title, "Run Quality Gate")

    def test_search_prioritizes_exact_domain_terms(self) -> None:
        results = rank_actions("quality gate", limit=3)
        self.assertEqual(results[0].id, "quality.run")

    def test_search_matches_keywords(self) -> None:
        results = rank_actions("atlas proof", limit=5)
        self.assertTrue(any(action.id.startswith("receipts.") for action in results))

    def test_search_finds_context_packet(self) -> None:
        results = rank_actions("context packet", limit=5)
        self.assertTrue(any(action.id.startswith("context.") for action in results))

    def test_search_finds_roadmap_milestone(self) -> None:
        results = rank_actions("next milestone", limit=5)
        self.assertTrue(any(action.id.startswith("roadmap.") for action in results))

    def test_search_finds_launch_package(self) -> None:
        results = rank_actions("launch package", limit=5)
        self.assertTrue(any(action.id.startswith("orchestrate.") for action in results))

    def test_search_finds_mesh_handoff_bus(self) -> None:
        action = action_by_id("mesh.sync_bus")
        self.assertIsNotNone(action)
        results = rank_actions("handoff bus", limit=5)
        self.assertTrue(any(item.id == "mesh.sync_bus" for item in results))

    def test_search_finds_tailnet_discovery(self) -> None:
        action = action_by_id("mesh.discover")
        self.assertIsNotNone(action)
        results = rank_actions("tailnet discover", limit=5)
        self.assertTrue(any(item.id == "mesh.discover" for item in results))

    def test_search_finds_bus_retry(self) -> None:
        action = action_by_id("mesh.retry_bus")
        self.assertIsNotNone(action)
        results = rank_actions("retry bus", limit=5)
        self.assertTrue(any(item.id == "mesh.retry_bus" for item in results))

    def test_search_finds_team_chat_refresh(self) -> None:
        action = action_by_id("mesh.refresh_chat")
        self.assertIsNotNone(action)
        results = rank_actions("team stream", limit=5)
        self.assertTrue(any(item.id == "mesh.refresh_chat" for item in results))

    def test_search_finds_team_chat_sync(self) -> None:
        action = action_by_id("mesh.sync_chat")
        self.assertIsNotNone(action)
        results = rank_actions("broadcast team stream", limit=5)
        self.assertTrue(any(item.id == "mesh.sync_chat" for item in results))

    def test_search_finds_team_chat_copy(self) -> None:
        action = action_by_id("mesh.copy_chat")
        self.assertIsNotNone(action)
        results = rank_actions("team stream copy", limit=5)
        self.assertTrue(any(item.id == "mesh.copy_chat" for item in results))

    def test_search_finds_mesh_repair(self) -> None:
        action = action_by_id("mesh.repair_bus")
        self.assertIsNotNone(action)
        results = rank_actions("repair bus", limit=5)
        self.assertTrue(any(item.id == "mesh.repair_bus" for item in results))

    def test_search_finds_mesh_repair_preview(self) -> None:
        action = action_by_id("mesh.preview_repair_bus")
        self.assertIsNotNone(action)
        results = rank_actions("preview repair bus", limit=5)
        self.assertTrue(any(item.id == "mesh.preview_repair_bus" for item in results))

    def test_search_finds_role_bootstrap(self) -> None:
        action = action_by_id("mesh.copy_role_bootstrap")
        self.assertIsNotNone(action)
        results = rank_actions("role bootstrap", limit=5)
        self.assertTrue(any(item.id == "mesh.copy_role_bootstrap" for item in results))

    def test_search_finds_team_summary_review(self) -> None:
        action = action_by_id("mesh.review_summary")
        self.assertIsNotNone(action)
        results = rank_actions("review team summary", limit=5)
        self.assertTrue(any(item.id == "mesh.review_summary" for item in results))

    def test_search_finds_launcher_diagnostics(self) -> None:
        action = action_by_id("launcher.diagnostics")
        self.assertIsNotNone(action)
        results = rank_actions("launcher diagnostics", limit=5)
        self.assertTrue(any(item.id == "launcher.diagnostics" for item in results))

    def test_search_finds_launcher_repair(self) -> None:
        action = action_by_id("launcher.repair")
        self.assertIsNotNone(action)
        results = rank_actions("repair launcher", limit=5)
        self.assertTrue(any(item.id == "launcher.repair" for item in results))

    def test_blank_search_returns_priority_order(self) -> None:
        results = rank_actions("", limit=2)
        self.assertEqual(results[0].id, "run.max")
        self.assertEqual(results[1].id, "quality.run")

    def test_groups_are_counted(self) -> None:
        groups = dict(action_groups())
        self.assertGreaterEqual(groups["Codex"], 1)
        self.assertEqual(sum(groups.values()), len(ACTION_SPECS))


if __name__ == "__main__":
    unittest.main()
