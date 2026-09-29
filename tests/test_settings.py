import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from settings import load_config, normalize_config, save_config
from tests.helpers import config


class SettingsTests(unittest.TestCase):
    def test_normalization_is_shared_and_does_not_mutate_input(self):
        original = config(dateToGo=["2099-11-05", "20991105"], placeFrom=" kmg ")
        normalized = normalize_config(original)
        self.assertEqual(normalized["dateToGo"], ["20991105"])
        self.assertEqual(normalized["placeFrom"], "KMG")
        self.assertEqual(original["placeFrom"], " kmg ")

    def test_invalid_enums_and_passengers_are_rejected(self):
        for change in ({"searchType": 9}, {"grade": 7}, {"sleepTime": True},
                       {"passengerList": [{"passengerType": "Adult", "passengerCount": 2}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize_config(config(**change), allow_expired=True)

    def test_expired_dates_can_be_loaded_for_editing_but_not_started(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            save_config(path, config(dateToGo=["20000101"]))
            self.assertEqual(load_config(path, allow_expired=True)["dateToGo"], ["20000101"])
            with self.assertRaises(ValueError):
                load_config(path)

    def test_failed_write_preserves_existing_file_and_removes_temporary(self):
        def fail(config, file, **kwargs):
            file.write("{")
            raise OSError("disk full")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"original": true}')
            with patch("settings.json.dump", side_effect=fail), self.assertRaises(OSError):
                save_config(path, config())
            self.assertEqual(path.read_text(), '{"original": true}')
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_failed_replace_preserves_original_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("original")
            with patch("settings.os.replace", side_effect=PermissionError), self.assertRaises(OSError):
                save_config(path, config())
            self.assertEqual(path.read_text(), "original")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_successful_save_roundtrips_normalized_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            saved = save_config(path, config(dateToGo=["2099-11-05"]))
            self.assertEqual(load_config(path), saved)
            self.assertEqual(json.loads(path.read_text())["dateToGo"], ["20991105"])

    def test_roundtrip_rejects_return_before_departure(self):
        with self.assertRaises(ValueError):
            normalize_config(config(flightWay="Roundtrip", returnDate="20991104"))
