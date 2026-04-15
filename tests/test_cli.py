import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import main_cli


class CliTests(unittest.TestCase):
    def test_export_prints_current_config_as_json(self):
        buf = io.StringIO()
        cfg = {"version": 8, "profiles": {}, "settings": {}}

        with patch("main_cli.load_config", return_value=cfg):
            rc = main_cli.export_config(stdout=buf)

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue()), cfg)

    def test_normalize_config_migrates_and_fills_defaults(self):
        legacy = {
            "version": 1,
            "active_profile": "default",
            "profiles": {
                "default": {
                    "label": "Default",
                    "mappings": {"xbutton1": "browser_back"},
                }
            },
            "settings": {},
        }

        normalized = main_cli.normalize_config(legacy)

        self.assertEqual(normalized["version"], 8)
        self.assertEqual(normalized["profiles"]["default"]["apps"], [])
        self.assertEqual(
            normalized["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )
        self.assertIn("language", normalized["settings"])

    def test_load_persists_normalized_config_then_starts_engine(self):
        raw = {
            "version": 1,
            "active_profile": "default",
            "profiles": {"default": {"label": "Default", "mappings": {}}},
            "settings": {},
        }

        saved = {}
        started = {}

        class _FakeEngine:
            def start(self):
                started["start"] = started.get("start", 0) + 1

            def stop(self):
                started["stop"] = started.get("stop", 0) + 1

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "import.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")

            stop_event = threading.Event()
            stop_event.set()

            with patch("main_cli.save_config", side_effect=lambda cfg: saved.setdefault("cfg", cfg)):
                rc = main_cli.load_config_and_start(
                    str(config_path),
                    stop_event=stop_event,
                    engine_factory=_FakeEngine,
                )

        self.assertEqual(rc, 0)
        self.assertEqual(saved["cfg"]["version"], 8)
        self.assertEqual(
            saved["cfg"]["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )
        self.assertEqual(started, {"start": 1, "stop": 1})

    def test_load_accepts_stdin_marker(self):
        raw = {
            "version": 8,
            "active_profile": "default",
            "profiles": {"default": {"label": "Default", "apps": [], "mappings": {}}},
            "settings": {},
        }
        saved = {}

        class _FakeEngine:
            def start(self):
                pass

            def stop(self):
                pass

        stop_event = threading.Event()
        stop_event.set()

        with (
            patch("sys.stdin", io.StringIO(json.dumps(raw))),
            patch("main_cli.save_config", side_effect=lambda cfg: saved.setdefault("cfg", cfg)),
        ):
            rc = main_cli.load_config_and_start(
                "-",
                stop_event=stop_event,
                engine_factory=_FakeEngine,
            )

        self.assertEqual(rc, 0)
        self.assertEqual(saved["cfg"]["version"], 8)


if __name__ == "__main__":
    unittest.main()
