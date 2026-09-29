from contextlib import redirect_stdout
import io
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app_logging import configure_logging
from flight_alert import main
from monitoring import MonitorService
from notifications import NotificationResult
from settings import save_config
from tests.helpers import calendar, clock, config


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.old_level = logging.getLogger().level
        self.addCleanup(self.close_logs)
        self.path = Path(self.directory.name) / "config.json"
        save_config(self.path, config())
        self.fetch = Mock(return_value=calendar())
        self.notify = Mock(return_value=NotificationResult(True))

    def close_logs(self):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            if getattr(handler, "_flight_alert", False):
                root.removeHandler(handler)
                handler.close()
        root.setLevel(self.old_level)

    def run_cli(self, *args):
        def service(cfg):
            return MonitorService(cfg, fetch=self.fetch, notify=self.notify, clock=clock)

        with redirect_stdout(io.StringIO()), patch("flight_alert.MonitorService", side_effect=service):
            return main(["--config", str(self.path), "--once", *args])

    def test_cli_once_no_notify_fetches_without_sending(self):
        self.assertEqual(self.run_cli("--no-notify"), 0)
        self.fetch.assert_called_once()
        self.notify.assert_not_called()
        log = (self.path.parent / "flight_alert.log").read_text(encoding="utf-8")
        self.assertIn("2099-11-05: CNY 630", log)
        self.assertNotIn("test-token", log)

    def test_cli_failed_notification_returns_nonzero(self):
        self.notify.return_value = NotificationResult(False, "test failure")
        self.assertEqual(self.run_cli(), 1)
        log = (self.path.parent / "flight_alert.log").read_text(encoding="utf-8")
        self.assertIn("test failure", log)

    def test_cli_invalid_config_does_not_start_network(self):
        self.path.write_text('{"searchType": 9}', encoding="utf-8")
        self.assertEqual(self.run_cli(), 1)
        self.fetch.assert_not_called()
        self.notify.assert_not_called()

    def test_keyboard_interrupt_sets_stop_event(self):
        with redirect_stdout(io.StringIO()), patch("flight_alert.run_monitor", side_effect=KeyboardInterrupt) as run:
            self.assertEqual(main(["--config", str(self.path)]), 0)
        self.assertTrue(run.call_args.args[1].is_set())

    def test_log_initialization_failure_returns_nonzero(self):
        with patch("flight_alert.configure_logging", side_effect=PermissionError("cannot write log")):
            self.assertEqual(main(["--config", str(self.path)]), 1)
        self.fetch.assert_not_called()

    def test_shared_logging_is_idempotent_and_records_tracebacks(self):
        configure_logging(self.directory.name)
        path = configure_logging(self.directory.name)
        log = logging.getLogger("test_gui")
        log.info("one copy of this message")
        try:
            raise RuntimeError("test GUI failure")
        except RuntimeError:
            log.exception("GUI exception")
        contents = path.read_text(encoding="utf-8")
        self.assertEqual(contents.count("one copy of this message"), 1)
        self.assertIn("Traceback", contents)
        self.assertIn("test GUI failure", contents)
