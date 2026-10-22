"""Checks for destination protection and rsync mirror behavior."""

import shutil
import shlex
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from dev.sync import sync_car


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "PI_HOST": "192.168.1.2",
            "PI_USER": "Drivion",
            "PI_PASSWORD": "literal $password",
        }

    def test_destination_and_password(self):
        command = sync_car.build_command(self.settings, True)
        self.assertEqual(command[-1], "Drivion@192.168.1.2:/home/Drivion/car/")
        self.assertIn("--dry-run", command)
        self.assertIn("--delete", command)
        self.assertNotIn(self.settings["PI_PASSWORD"], " ".join(command))
        for destination in ("/", "/home/Drivion", "/home/Drivion/car/../", "/tmp/car"):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                sync_car.build_command(dict(self.settings, PI_CAR_PATH=destination))

    def test_key_authentication_needs_no_password(self):
        settings = dict(self.settings)
        settings.pop("PI_PASSWORD")
        self.assertEqual(sync_car.build_command(settings)[0], "rsync")
        self.assertNotIn("sshpass", sync_car.build_command(settings))
        self.assertEqual(
            sync_car.build_key_command(settings)[-1], "Drivion@192.168.1.2"
        )
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder) / "existing.pub"
            public.write_text("ssh-ed25519 example")
            command = sync_car.build_key_command(settings, public)
            self.assertIn(str(public.resolve()), command)
            with self.assertRaises(ValueError):
                sync_car.build_key_command(settings, Path(folder) / "private")

    @unittest.skipUnless(shutil.which("rsync"), "rsync is required")
    def test_mirror_preserves_environment_and_home(self):
        options = sync_car.tool_settings()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, home = root / "source", root / "home"
            target = home / "car"
            source.mkdir()
            target.mkdir(parents=True)
            (source / "drive.py").write_text("new")
            (source / "drive.py").chmod(0o755)
            (target / "old.py").write_text("old")
            (home / "personal.txt").write_text("keep")
            environment = target / "system/.venv"
            environment.mkdir(parents=True)
            (environment / "marker").write_text("keep")
            (target / ".env").write_text("keep")
            diagnostics = target / "system/hardware_tests/logs/check.log"
            diagnostics.parent.mkdir(parents=True)
            diagnostics.write_text("saved diagnostics")
            (source / "config.toml").write_text("workstation defaults")
            (target / "config.toml").write_text("Pi calibration")
            for name in ("logs", "build"):
                generated = target / "system/arduino" / name
                generated.mkdir(parents=True)
                (generated / "marker").write_text("keep")
            with patch.object(sync_car, "CAR_DIR", source):
                command = sync_car.build_command(self.settings, options=options)
            # Exercise the exact transfer flags and exclusions against a local destination.
            transfer = command[: command.index("-e")]
            subprocess.run(
                transfer + ["--dry-run", str(source) + "/", str(target) + "/"],
                capture_output=True,
                check=True,
            )
            self.assertTrue((target / "old.py").exists())
            subprocess.run(
                transfer + [str(source) + "/", str(target) + "/"],
                capture_output=True,
                check=True,
            )
            self.assertFalse((target / "old.py").exists())
            self.assertEqual((target / "drive.py").read_text(), "new")
            self.assertEqual(diagnostics.read_text(), "saved diagnostics")
            self.assertEqual((target / "config.toml").read_text(), "Pi calibration")
            replacement = sync_car.build_command(self.settings, replace_config=True)
            subprocess.run(
                replacement[: replacement.index("-e")]
                + [str(source) + "/", str(target) + "/"],
                check=True,
                capture_output=True,
            )
            self.assertEqual(
                (target / "config.toml").read_text(), "workstation defaults"
            )
            self.assertTrue((target / "drive.py").stat().st_mode & 0o100)
            self.assertEqual((environment / "marker").read_text(), "keep")
            self.assertEqual((target / ".env").read_text(), "keep")
            self.assertEqual((home / "personal.txt").read_text(), "keep")
            for name in ("logs", "build"):
                self.assertEqual(
                    (target / "system/arduino" / name / "marker").read_text(), "keep"
                )

    def test_ssh_arguments_preserve_public_key_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder) / "controller identity.pub"
            public.write_text("ssh-ed25519 example")
            settings = dict(self.settings, PI_SSH_PUBLIC_KEY=str(public))
            command = sync_car.build_command(settings)
            ssh = sync_car.ssh_command(settings)
            self.assertEqual(shlex.split(command[command.index("-e") + 1]), ssh)
            self.assertEqual(ssh[-1], str(public.resolve()))
            self.assertNotIn("-i", sync_car.ssh_command(settings, password=True))

    def test_import_needs_no_configuration_files(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from unittest.mock import patch; "
                    "from pathlib import Path; "
                    "guard = patch.object(Path, 'open', side_effect=AssertionError('configuration read at import')); "
                    "guard.start(); import dev.sync.sync_car; import dev.ansible.run"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path(sync_car.__file__).resolve().parents[2],
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
