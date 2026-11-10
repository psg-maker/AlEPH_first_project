"""Apply this reviewed file set to the existing feature branch. Never touches .env.local."""
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def checksum(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(target, dry_run=False):
    source = Path(__file__).resolve().parent
    target = target.resolve(strict=True)
    manifest = json.loads(source.joinpath('manifest.json').read_text(encoding='utf-8'))
    branch = subprocess.run(['git', '-C', str(target), 'branch', '--show-current'],
                            capture_output=True, text=True, check=True).stdout.strip()
    if branch != 'aleph_eight_project':
        raise SystemExit('Switch to aleph_eight_project before applying.')
    changes = []
    for name, entry in manifest.items():
        destination = target.joinpath(name).resolve()
        if not destination.is_relative_to(target): raise SystemExit('Invalid target path.')
        if checksum(source / name) != entry['sha256']: raise SystemExit('Package checksum mismatch: ' + name)
        if destination.exists():
            actual = checksum(destination)
            if actual == entry['sha256']: continue  # Already applied; keep untouched.
            if actual != entry.get('original_sha256'):
                raise SystemExit('Existing file has changed; nothing applied. Check: ' + name)
        elif entry.get('original_sha256'):
            raise SystemExit('Expected original file is missing: ' + name)
        changes.append(name)
    if dry_run:
        print('Preflight OK. Files to apply:', len(changes))
        return
    backup = target / ('.aleph8-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    copied = []
    try:
        for name in changes:
            destination = target / name
            if destination.exists():
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            destination.parent.mkdir(parents=True, exist_ok=True)
            copied.append(name)
            shutil.copy2(source / name, destination)
    except Exception:
        for name in reversed(copied):
            destination = target / name
            saved = backup / name
            if saved.exists(): shutil.copy2(saved, destination)
            else: destination.unlink(missing_ok=True)
        raise
    print('Applied', len(changes), 'files. Environment files were not changed.')
    if backup.exists(): print('Original-file backup:', backup)


if __name__ == '__main__':
    apply(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd(), '--check' in sys.argv[2:])
