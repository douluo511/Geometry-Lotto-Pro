from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stock_ai.pipeline as pipeline
from stock_ai.utils import close_logging, setup_logging

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    first = setup_logging(root / "first")
    second = setup_logging(root / "second")
    first.info("first-only")
    second.info("second-only")
    close_logging(first)
    second.info("second-still-active")
    close_logging(second)
    assert not first.handlers and not second.handlers
    first_log = root / "first" / "stock_ai.log"
    second_log = root / "second" / "stock_ai.log"
    assert "first-only" in first_log.read_text(encoding="utf-8")
    assert "second-only" not in first_log.read_text(encoding="utf-8")
    assert "second-still-active" in second_log.read_text(encoding="utf-8")
    # Windows refuses rename/delete while a FileHandler still owns the file.
    first_log.rename(root / "first-renamed.log")
    second_log.unlink()

    for fail in [False, True]:
        case = root / ("failure" if fail else "success")
        case.mkdir()
        (case / "state").mkdir()
        captured = []
        def logging_factory(log_dir):
            logger = setup_logging(log_dir)
            captured.append(logger)
            return logger
        def execute(*args):
            args[1].info("bound-session-evidence")
            if fail:
                raise RuntimeError("injected-session-failure")
            return "result"
        with patch.object(pipeline, "ROOT", case), patch.object(pipeline, "load_config", return_value={"safety": {}}), patch.object(pipeline, "ensure_dirs", return_value=None), patch.object(pipeline, "setup_logging", side_effect=logging_factory), patch.object(pipeline, "_run_locked", side_effect=execute):
            if fail:
                try:
                    pipeline.run(False, False)
                except RuntimeError as error:
                    assert str(error) == "injected-session-failure"
                else:
                    raise AssertionError("pipeline swallowed the failure")
            else:
                assert pipeline.run(False, False) == "result"
        assert not captured[0].handlers
        assert not (case / "state" / "daily.lock").exists()
        log = case / "logs" / "stock_ai.log"
        assert "bound-session-evidence" in log.read_text(encoding="utf-8")
        log.unlink()

print("LOGGING SESSION ISOLATION / SUCCESS / FAILURE HANDLE RELEASE TEST PASS")
