# Smoke test: every module under app/ must import cleanly.
# This catches circular imports and typos introduced in future phases.
import importlib
import pkgutil


def test_all_app_modules_import() -> None:
    import app

    failures = []
    for mod in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # noqa: BLE001 - we want the message
            failures.append((mod.name, repr(exc)))
    assert not failures, f"Import failures: {failures}"
