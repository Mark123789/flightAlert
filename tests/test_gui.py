from queue import Queue
from threading import Event
import unittest
from unittest.mock import Mock, patch

import tkinter as tk

from flight_alert_gui import FlightAlertApp, parse_monitor_config
from monitoring import MonitorEvent
from tests.helpers import config


class Variable:
    def __init__(self, value="unchanged"):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class GUITests(unittest.TestCase):
    def app(self):
        app = FlightAlertApp.__new__(FlightAlertApp)
        app.root = Mock()
        app.root.after.return_value = "timer"
        app.running, app.closing = True, False
        app.stop_event = Event()
        app.start_button, app.stop_button = Mock(), Mock()
        app.monitor_thread = Mock()
        app.monitor_thread.is_alive.return_value = True
        app._poll_after_id, app._finish_after_id = "poll", None
        app._finish_message = "监控已停止"
        app._generation = 1
        app._events = Queue()
        app._status_text = Mock(return_value="status")
        app._update_status = Mock()
        app._update_prices_display = Mock()
        app._log = Mock()
        return app

    def test_invalid_loaded_config_does_not_mutate_any_field(self):
        app = self.app()
        app.dates_var = Variable()
        for fields in ({"searchType": 9}, {"grade": 7}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                app._fill_config_inputs(config(**fields))
            self.assertEqual(app.dates_var.get(), "unchanged")

    def test_gui_and_cli_share_enum_validation(self):
        with self.assertRaises(ValueError):
            parse_monitor_config("20991105", "KMG", "TNA", "Oneway", "600", "50", "", grade=7)

    def test_close_waits_for_worker_then_cancels_callbacks_and_destroys(self):
        app = self.app()
        app._on_close()
        self.assertTrue(app.stop_event.is_set())
        self.assertTrue(app.closing)
        app.root.after_cancel.assert_called_with("poll")
        app.root.destroy.assert_not_called()
        app.monitor_thread.is_alive.return_value = False
        app._poll_worker_exit()
        app.root.destroy.assert_called_once()
        self.assertIsNone(app._finish_after_id)

    def test_close_without_worker_destroys_immediately(self):
        app = self.app()
        app.monitor_thread = None
        app._on_close()
        app.root.destroy.assert_called_once()

    def test_start_failure_rolls_back_buttons_and_running_state(self):
        app = self.app()
        app.running = False
        app.monitor_thread = None
        app._build_config_from_inputs = Mock(return_value=config())
        app._fill_config_inputs = Mock()
        app._price_header_text = Mock(return_value="header")
        with patch("flight_alert_gui.threading.Thread") as thread, patch("flight_alert_gui.messagebox"):
            thread.return_value.start.side_effect = RuntimeError("cannot start thread")
            app._start_monitoring()
        self.assertFalse(app.running)
        self.assertTrue(app.stop_event.is_set())
        app.start_button.config.assert_called_with(state=tk.NORMAL)
        app.stop_button.config.assert_called_with(state=tk.DISABLED)

    def test_old_run_events_cannot_stop_a_new_run(self):
        app = self.app()
        app._events.put((0, MonitorEvent("finished", "old run finished")))
        app._events.put((1, MonitorEvent("phase", "new run")))
        app._poll_events()
        self.assertTrue(app.running)
        self.assertFalse(app.stop_event.is_set())
        app._status_text.assert_called_with("new run")

    def test_finished_event_restores_buttons(self):
        app = self.app()
        app.monitor_thread.is_alive.return_value = False
        app._handle_monitor_event(MonitorEvent("finished", "接口格式错误"))
        self.assertFalse(app.running)
        app.start_button.config.assert_called_with(state=tk.NORMAL)
        app.stop_button.config.assert_called_with(state=tk.DISABLED)
        app._status_text.assert_called_with("接口格式错误")
