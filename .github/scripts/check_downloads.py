"""Reject stale public download aliases; optionally check their anonymous URLs."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from release_support import inventory, inventory_sha256

ALIASES = ('MathModel-Copilot-latest.zip', 'MathModel-Copilot-v0.3-Preview.zip')
URL = 'https://github.com/Odyphus/MathModel-Copilot/raw/refs/heads/main/downloads/'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(root=ROOT, remote=False):
    root = Path(root)
    downloads = root / 'downloads'
    index = json.loads((downloads / 'release-index.json').read_text(encoding='utf-8'))
    metadata = json.loads((root / 'RELEASE_METADATA.json').read_text(encoding='utf-8'))
    require(index['stable_download'] == ALIASES[0] and index['compatible_download'] == ALIASES[1],
            'Published download filenames must remain fixed, including the old WeChat link')
    version = index['current_version']
    require(version == metadata['version'], 'Download index does not match source version')
    require(index['versioned_download'] == f'MathModel-Copilot-v{version}.zip', 'Invalid versioned download name')
    data = (downloads / index['versioned_download']).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    require(sha == index['sha256'] and len(data) == index['bytes'], 'Download index hash or size mismatch')
    for name in ALIASES:
        require((downloads / name).read_bytes() == data, f'{name} is stale: replace it with the validated runtime package')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        require(archive.testzip() is None, 'ZIP CRC failed')
        files = inventory(root, profile='runtime')
        manifest_name = 'mathmodel-copilot/RELEASE_MANIFEST.json'
        manifest = json.loads(archive.read(manifest_name))
        require(manifest['distribution_profile'] == 'runtime' and manifest['version'] == version, 'Not the current runtime package')
        require(manifest['files'] == files, 'Runtime source changed without rebuilding the download package')
        require(manifest['source_manifest_sha256'] == inventory_sha256(files) == index['source_manifest_sha256'], 'Manifest digest mismatch')
        require(index['manifest_files'] == len(files), 'Manifest file count mismatch')
        expected = ['mathmodel-copilot/' + item['path'] for item in files] + [manifest_name]
        require(sorted(archive.namelist()) == sorted(expected), 'ZIP member set mismatch')
        require([n for n in expected if n.endswith('/SKILL.md')] == ['mathmodel-copilot/SKILL.md'], 'Expected exactly one Skill entry')
        for item in files:
            require(archive.read('mathmodel-copilot/' + item['path']) == (root / item['path']).read_bytes(), 'ZIP content mismatch: ' + item['path'])
    sums = {}
    for line in (downloads / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        if line.strip():
            digest, name = line.split('  ', 1)
            require(name not in sums, 'Duplicate checksum entry')
            sums[name] = digest
    for name in (*ALIASES, index['versioned_download']):
        require(sums.get(name) == sha, 'Checksum missing or stale: ' + name)
    for item in index.get('history', []):
        path = Path(item['path'])
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in item['path'], 'Invalid history path')
        require(hashlib.sha256((downloads / path).read_bytes()).hexdigest() == item['sha256'] == sums.get(item['path']), 'Historical package changed: ' + item['path'])
    if remote:
        for name in ALIASES:
            # Check the exact published URL, without a cache-busting query.
            with urllib.request.urlopen(URL + name, timeout=60) as response:
                require(response.status == 200 and response.read() == data,
                        'Public download still differs (possibly CDN cache); retry after refresh: ' + name)
    return {'version': version, 'sha256': sha, 'fixed_aliases': list(ALIASES), 'runtime_source_matches': True, 'anonymous_downloads_checked': remote}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', action='store_true', help='After pushing, anonymously read both exact fixed URLs')
    args = parser.parse_args()
    try:
        print(json.dumps(check(remote=args.remote), indent=2))
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc) + '\n')
