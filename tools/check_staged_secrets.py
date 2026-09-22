"""Inspect staged blobs (or Git history) without printing secret values."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [re.compile(r'AIza[0-9A-Za-z_-]{25,}'),
            re.compile(r'(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}'),
            re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
            re.compile(r'(?i)(?:https?|postgres(?:ql)?|mysql)://[^\s/:]+:[^\s/@]+@')]
ASSIGNMENT = re.compile(r'''(?im)^\s*["']?(?:[\w]*API_KEY|[\w]*PASSWORD|[\w]*ACCESS_TOKEN|[\w]*SECRET)["']?\s*[:=]\s*["']([^"'\n]+)["']''')
PLACEHOLDERS = ('your_', 'mock-', 'local-test-', 'test-', '...', 'YOUR_')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def known_local_secrets():
    # This reads only to compare; neither values nor matching lines are printed.
    from dotenv import dotenv_values
    values = []
    if (ROOT / '.env').exists():
        for key, value in dotenv_values(ROOT / '.env').items():
            if value and re.search('KEY|PASSWORD|TOKEN|SECRET', key) and len(value) >= 8:
                values.append(value)
    return values


def inspect(path, text, known):
    reasons = []
    parts = Path(path).parts
    if ('data' in parts or 'outputs' in parts or '.venv' in parts or 'venv' in parts
            or '__pycache__' in parts or Path(path).name == 'secrets.toml'
            or (Path(path).name.startswith('.env') and Path(path).name != '.env.example')):
        reasons.append('private/generated path')
    if any(secret in text for secret in known):
        reasons.append('matches local secret')
    if any(pattern.search(text) for pattern in PATTERNS):
        reasons.append('credential signature')
    for match in ASSIGNMENT.finditer(text):
        if not match.group(1).startswith(PLACEHOLDERS):
            reasons.append('literal credential assignment')
    return sorted(set(reasons))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true')
    args = parser.parse_args()
    known = known_local_secrets()
    snapshots = git('rev-list', '--all').decode().splitlines() if args.history else [None]
    failures = []
    count = 0
    for revision in snapshots:
        paths = (git('ls-tree', '-r', '--name-only', '-z', revision) if revision else
                 git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'))
        for raw_path in paths.split(b'\0'):
            if not raw_path:
                continue
            path = raw_path.decode()
            blob = git('show', f'{revision or ""}:{path}').decode('utf-8', errors='replace')
            count += 1
            reasons = inspect(path, blob, known)
            if reasons:
                failures.append((path, reasons))
    for path, reasons in failures:
        print('BLOCKED:', path, '; '.join(reasons))
    print(f'Checked {count} blobs; findings: {len(failures)}. Values suppressed.')
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
