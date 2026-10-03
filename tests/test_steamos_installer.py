from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('steamos_installer', Path(__file__).resolve().parents[1] / 'tools/install/steamos.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class SteamOSInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name) / 'home with spaces'
        base = root / 'runtime'
        base.mkdir(parents=True)
        paths = dict(BASE=base, CURRENT=base/'current', SERVICE=root/'g13d.service',
                     LAUNCHER=root/'launcher', DESKTOP=root/'desktop', RULE=root/'rule', MODULE=root/'module')
        self.globals = patch.multiple(installer, **paths)
        self.globals.start()
        self.addCleanup(self.globals.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_unmanaged_service_is_never_overwritten(self):
        installer.SERVICE.write_text('User-created service')
        with self.assertRaisesRegex(RuntimeError, 'unmanaged'):
            installer.protect_existing()
        self.assertEqual(installer.SERVICE.read_text(), 'User-created service')

    def test_symlink_setup_file_is_never_overwritten(self):
        target = installer.BASE/'external'
        target.write_text(installer.MARKER)
        installer.SERVICE.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, 'unmanaged'):
            installer.protect_existing()

    def test_failed_first_activation_removes_service_enablement(self):
        def run(command, **kwargs):
            if command[:3] == ['systemctl', '--user', 'enable']:
                raise subprocess.CalledProcessError(1, command)
        with patch.object(installer, 'preflight', return_value='1.9.0'), \
             patch.object(installer, 'run', side_effect=run), \
             patch.object(installer.subprocess, 'run') as cleanup, \
             patch.object(installer.os, 'access', return_value=True):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.install()
        cleanup.assert_any_call(['systemctl', '--user', 'disable', 'g13d'])
        self.assertFalse(installer.SERVICE.exists())
        self.assertFalse(installer.CURRENT.exists())
        self.assertFalse(list(installer.BASE.glob('runtime-*')))

    def test_install_then_reinstall_uses_stable_launcher_and_keeps_profiles(self):
        profiles = installer.BASE.parent / 'profiles'
        profiles.mkdir()
        (profiles/'custom.toml').write_text('user profile')
        with patch.object(installer, 'preflight', return_value='1.9.0'), \
             patch.object(installer, 'run') as run, patch.object(installer.os, 'access', return_value=True):
            installer.install()
            old = installer.CURRENT.resolve()
            self.assertTrue(old.is_dir())
            self.assertIn('"', installer.SERVICE.read_text())
            self.assertIn('current/bin/g13d', installer.SERVICE.read_text())
            installer.install()
            self.assertNotEqual(old, installer.CURRENT.resolve())
            self.assertFalse(old.exists())
            commands = [call.args[0] for call in run.call_args_list]
            pip = next(cmd for cmd in commands if 'install' in cmd and '--only-binary=:all:' in cmd)
            self.assertIn('--constraint', pip)
        self.assertEqual((profiles/'custom.toml').read_text(), 'user profile')

    def test_failed_dependency_install_leaves_existing_runtime_intact(self):
        old = installer.BASE/'runtime-old'
        old.mkdir()
        installer.point_current(old)
        installer.SERVICE.write_text(installer.MARKER+'\noriginal service')
        with patch.object(installer, 'preflight', return_value='1.9.0'), \
             patch.object(installer, 'run', side_effect=subprocess.CalledProcessError(1, 'pip')):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.install()
        self.assertEqual(installer.CURRENT.resolve(), old)
        self.assertIn('original service', installer.SERVICE.read_text())
        self.assertEqual(list(installer.BASE.glob('runtime-*')), [old])

    def test_service_start_failure_restores_previous_runtime_and_service(self):
        old = installer.BASE/'runtime-old'
        old.mkdir()
        installer.point_current(old)
        original = installer.MARKER+'\noriginal service'
        installer.SERVICE.write_text(original)
        def run(command, **kwargs):
            if command[:3] == ['systemctl', '--user', 'enable']:
                raise subprocess.CalledProcessError(1, command)
        with patch.object(installer, 'preflight', return_value='1.9.0'), \
             patch.object(installer, 'run', side_effect=run), \
             patch.object(installer.subprocess, 'run'), \
             patch.object(installer.os, 'access', return_value=True):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.install()
        self.assertEqual(installer.CURRENT.resolve(), old)
        self.assertEqual(installer.SERVICE.read_text(), original)
        self.assertFalse(installer.DESKTOP.exists())
        self.assertFalse(installer.LAUNCHER.exists())

    def test_uninstall_preserves_profile_files(self):
        runtime = installer.BASE/'runtime-test'
        runtime.mkdir()
        installer.point_current(runtime)
        installer.SERVICE.write_text(installer.MARKER)
        profile = installer.BASE.parent/'custom.toml'
        profile.write_text('keep')
        with patch.object(installer, 'run'):
            installer.uninstall()
        self.assertFalse(installer.SERVICE.exists())
        self.assertFalse(installer.CURRENT.exists())
        self.assertFalse(runtime.exists())
        self.assertEqual(profile.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
