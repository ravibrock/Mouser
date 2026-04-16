import io
import json
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main_cli


class CliTests(unittest.TestCase):
    def test_wait_for_headless_activity_pumps_macos_run_loop(self):
        stop_event = main_cli.threading.Event()
        calls = []

        class _QuartzStub:
            kCFRunLoopDefaultMode = "default"

            @staticmethod
            def CFRunLoopRunInMode(mode, seconds, return_after_source_handled):
                calls.append((mode, seconds, return_after_source_handled))
                stop_event.set()

        with (
            patch("main_cli.sys.platform", "darwin"),
            patch.object(main_cli, "Quartz", _QuartzStub),
        ):
            main_cli._wait_for_headless_activity(stop_event, timeout_s=0.5)

        self.assertEqual(calls, [("default", 0.1, False)])

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

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "import.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")

            with (
                patch("main_cli.save_config", side_effect=lambda cfg: saved.setdefault("cfg", cfg)),
                patch("main_cli.start_background_service", return_value=0) as start_background_service,
            ):
                rc = main_cli.load_config_and_start(
                    str(config_path),
                )

        self.assertEqual(rc, 0)
        self.assertEqual(saved["cfg"]["version"], 8)
        self.assertEqual(
            saved["cfg"]["profiles"]["default"]["mappings"]["mode_shift"],
            "switch_scroll_mode",
        )
        start_background_service.assert_called_once_with()

    def test_load_accepts_stdin_marker(self):
        raw = {
            "version": 8,
            "active_profile": "default",
            "profiles": {"default": {"label": "Default", "apps": [], "mappings": {}}},
            "settings": {},
        }
        saved = {}

        with (
            patch("sys.stdin", io.StringIO(json.dumps(raw))),
            patch("main_cli.save_config", side_effect=lambda cfg: saved.setdefault("cfg", cfg)),
            patch("main_cli.start_background_service", return_value=0) as start_background_service,
        ):
            rc = main_cli.load_config_and_start(
                "-",
            )

        self.assertEqual(rc, 0)
        self.assertEqual(saved["cfg"]["version"], 8)
        start_background_service.assert_called_once_with()

    def test_start_writes_launch_agent_and_bootstraps_it(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plist_path = Path(tmp_dir) / main_cli.CLI_SERVICE_PLIST_NAME
            launchctl_calls = []

            def _fake_launchctl(args):
                launchctl_calls.append(args)
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with (
                patch("sys.platform", "darwin"),
                patch("main_cli._service_plist_path", return_value=str(plist_path)),
                patch("main_cli._launchctl_run", side_effect=_fake_launchctl),
            ):
                rc = main_cli.start_background_service()

        self.assertEqual(rc, 0)
        self.assertEqual(
            launchctl_calls,
            [["launchctl", "bootstrap", f"gui/{main_cli.os.getuid()}", str(plist_path)]],
        )
        payload = plistlib.loads(plist_path.read_bytes())
        self.assertEqual(payload["Label"], main_cli.CLI_SERVICE_LABEL)
        self.assertEqual(payload["ProgramArguments"], main_cli._service_program_arguments())
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])

    def test_stop_boots_out_and_removes_launch_agent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plist_path = Path(tmp_dir) / main_cli.CLI_SERVICE_PLIST_NAME
            plist_path.write_text("placeholder", encoding="utf-8")
            launchctl_calls = []

            def _fake_launchctl(args):
                launchctl_calls.append(args)
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with (
                patch("sys.platform", "darwin"),
                patch("main_cli._service_plist_path", return_value=str(plist_path)),
                patch("main_cli._launchctl_run", side_effect=_fake_launchctl),
            ):
                rc = main_cli.stop_background_service()

        self.assertEqual(rc, 0)
        self.assertEqual(
            launchctl_calls,
            [["launchctl", "bootout", f"gui/{main_cli.os.getuid()}", str(plist_path)]],
        )
        self.assertFalse(plist_path.exists())

    def test_main_start_and_stop_dispatch_to_service_helpers(self):
        with (
            patch("main_cli.setup_logging"),
            patch("main_cli.start_background_service", return_value=0) as start_background_service,
            patch("main_cli.stop_background_service", return_value=0) as stop_background_service,
        ):
            self.assertEqual(main_cli.main(["start"]), 0)
            self.assertEqual(main_cli.main(["stop"]), 0)

        start_background_service.assert_called_once_with()
        stop_background_service.assert_called_once_with()

    def test_main_internal_run_dispatches_to_headless_runner(self):
        with (
            patch("main_cli.setup_logging"),
            patch("main_cli.run_headless_instance", return_value=0) as run_headless_instance,
        ):
            self.assertEqual(main_cli.main(["_run"]), 0)

        run_headless_instance.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
