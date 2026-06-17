import tempfile
import unittest
from pathlib import Path

from codex_sessions import (
    load_sessions,
    new_session,
    remove_session,
    replace_session,
    save_sessions,
    session_title,
    upsert_session,
)


class SessionWorkspaceTests(unittest.TestCase):
    def test_session_title_compacts_prompt(self) -> None:
        self.assertEqual(session_title("  build   the app  "), "build the app")
        self.assertEqual(session_title(""), "New Session")

    def test_create_and_replace_session(self) -> None:
        session = new_session("/tmp/project", "maximum-power", "interactive", "build this")
        updated = replace_session(
            session,
            project="/tmp/project",
            profile="deep-review",
            action="review",
            prompt="review this",
            status="running",
        )
        self.assertEqual(updated.id, session.id)
        self.assertEqual(updated.profile, "deep-review")
        self.assertEqual(updated.action, "review")
        self.assertEqual(updated.status, "running")

    def test_save_load_upsert_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions.json"
            one = new_session("/a", "maximum-power", "interactive", "one")
            two = new_session("/b", "deep-review", "review", "two")
            sessions = upsert_session([], one)
            sessions = upsert_session(sessions, two)
            save_sessions(path, sessions)
            loaded = load_sessions(path)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(remove_session(loaded, one.id)[0].id, two.id)


if __name__ == "__main__":
    unittest.main()
