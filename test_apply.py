import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'package'; self.source.mkdir()
        self.target = root / 'project'; self.target.mkdir()
        subprocess.run(['git', 'init', '-b', 'aleph_eight_project', str(self.target)],
                       check=True, capture_output=True)
        shutil.copy2(Path(__file__).with_name('APPLY.py'), self.source / 'APPLY.py')
        original = b'original source\n'; updated = b'updated source\n'
        (self.target / 'main.py').write_bytes(original)
        (self.source / 'main.py').write_bytes(updated)
        (self.target / '.env.local').write_text('secret-sentinel')
        manifest = {'main.py': {'sha256': hashlib.sha256(updated).hexdigest(),
                                'original_sha256': hashlib.sha256(original).hexdigest()}}
        (self.source / 'manifest.json').write_text(json.dumps(manifest))
        spec = importlib.util.spec_from_file_location('installer_fixture', self.source / 'APPLY.py')
        self.installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.installer)

    def test_failed_partial_copy_restores_original(self):
        original_copy = shutil.copy2
        def fail_after_truncating(source, target, *args, **kwargs):
            if Path(source) == self.source / 'main.py':
                Path(target).write_bytes(b'partial')
                raise OSError('simulated full disk')
            return original_copy(source, target, *args, **kwargs)
        with patch.object(self.installer.shutil, 'copy2', fail_after_truncating):
            with self.assertRaises(OSError): self.installer.apply(self.target)
        self.assertEqual((self.target / 'main.py').read_bytes(), b'original source\n')

    def test_apply_preserves_environment_and_is_idempotent(self):
        self.installer.apply(self.target)
        self.installer.apply(self.target)
        self.assertEqual((self.target / 'main.py').read_bytes(), b'updated source\n')
        self.assertEqual((self.target / '.env.local').read_text(), 'secret-sentinel')
        self.assertEqual(len(list(self.target.glob('.aleph8-backup-*'))), 1)

    def test_changed_source_is_rejected_without_overwrite(self):
        (self.target / 'main.py').write_bytes(b'user changes')
        with self.assertRaises(SystemExit): self.installer.apply(self.target)
        self.assertEqual((self.target / 'main.py').read_bytes(), b'user changes')


if __name__ == '__main__': unittest.main()
