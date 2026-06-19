import ast
import unittest
from pathlib import Path


def _method_named(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"method {name!r} not found")


def _thread_start_targets_worker(node: ast.AST) -> bool:
    if not isinstance(node, ast.Expr):
        return False
    call = node.value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        return False
    if call.func.attr != "start":
        return False
    thread_call = call.func.value
    if not isinstance(thread_call, ast.Call):
        return False
    thread_func = thread_call.func
    if not isinstance(thread_func, ast.Attribute) or thread_func.attr != "Thread":
        return False
    return any(
        keyword.arg == "target"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "worker"
        for keyword in thread_call.keywords
    )


class GuiSourceTests(unittest.TestCase):
    def test_tailnet_discovery_starts_worker_from_handler_scope(self) -> None:
        source = Path("codex_gui.py").read_text(encoding="utf-8")
        method = _method_named(ast.parse(source), "on_discover_tailnet")
        worker = next(
            node for node in method.body
            if isinstance(node, ast.FunctionDef) and node.name == "worker"
        )

        self.assertTrue(any(_thread_start_targets_worker(node) for node in method.body))
        self.assertFalse(any(_thread_start_targets_worker(node) for node in worker.body))


if __name__ == "__main__":
    unittest.main()
