"""Manual CI routing and pinned Python/Tk in an exact disposable job directory."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOS = {'samuel-zhang01/VideoMate': 'videomate',
         'samuel-zhang01/VideoMate-private': 'videomate-private'}
PLATFORMS = (
    ('windows-latest', 'windows-x86_64', 'x64', True, True),
    ('macos-15', 'macos-arm64', 'arm64', True, False),
    ('ubuntu-24.04', 'linux-x86_64', 'x64', False, False),
    ('ubuntu-24.04-arm', 'linux-arm64', 'arm64', False, True),
)
# Official publisher release-asset metadata, not an unverified latest download.
PYTHON_311 = {
    'macos-arm64': ('aarch64-apple-darwin', 'e1d745b07b6acc0641dbb3237d3c5953deeeed182141bab2242684076fd86547'),
    'linux-x86_64': ('x86_64-unknown-linux-gnu', '68c6739376b65258dee5058ccf6777232fe38d31a578965ae8bda327ec7da3a8'),
}


def matrix(kind, repository, include_hosted=False):
    slug = REPOS[repository]  # A fork cannot request the owner's local listener.
    rows = []
    for os_name, tag, arch, desktop, hosted in PLATFORMS:
        if hosted and not include_hosted:
            continue
        runners = [os_name] if hosted else [
            'local-macos' if tag.startswith('macos-') else 'deploy-vps', slug]
        for python in (('3.11', '3.13') if kind == 'tests' else ('3.13',)):
            rows.append({'os': os_name, 'platform': tag, 'architecture': arch,
                         'desktop': desktop, 'hosted': hosted, 'python': python,
                         'runner': runners})
    return {'include': rows}


def install_module():
    spec = importlib.util.spec_from_file_location('ci_python_installer', ROOT / 'tools/install_python.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runtime_spec(version, tag):
    if version == '3.13':
        return json.loads((ROOT / 'dependencies/python-sources.json').read_text())['platforms'][tag]
    target, sha = PYTHON_311[tag]
    filename = f'cpython-3.11.16+20260924-{target}-install_only_stripped.tar.gz'
    return {'version': '3.11.16', 'filename': filename, 'sha256': sha,
            'url': 'https://github.com/astral-sh/python-build-standalone/releases/download/20260924/'
                   + filename.replace('+', '%2B')}


def prepare_runtime(version, parent):
    system, machine = platform.system(), platform.machine().lower()
    tags = {('Darwin', 'arm64'): 'macos-arm64', ('Linux', 'x86_64'): 'linux-x86_64'}
    tag = tags[(system, machine)]
    spec = runtime_spec(version, tag)
    directory = Path(tempfile.mkdtemp(prefix='videomate-ci-python-', dir=parent)).resolve()
    directory.chmod(0o700)
    try:
        archive = directory / 'runtime.tar.gz'
        digest, count = hashlib.sha256(), 0
        with urllib.request.urlopen(spec['url'], timeout=60) as response, archive.open('xb') as output:
            if not response.geturl().startswith('https://'):
                raise ValueError('Public runtime download requires HTTPS')
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > 256 * 1024 * 1024:
                    raise ValueError('Public runtime archive exceeds limit')
                digest.update(chunk); output.write(chunk)
        if digest.hexdigest() != spec['sha256']:
            raise ValueError('Public runtime archive checksum mismatch')
        install_module().extract_runtime(archive, directory)
        executable = directory / 'python/bin/python3'
        subprocess.run([str(executable), '-c',
                        'import sys,tkinter; assert sys.version_info[:2] == ' + repr(tuple(map(int, version.split('.'))))
                        + '; print(sys.version.split()[0]); print("Tk", tkinter.Tcl().call("info", "patchlevel"))'], check=True)
        archive.unlink()
        (directory / '.videomate-ci-owned').write_text('public-software-only\n')
        if os.environ.get('GITHUB_PATH') and os.environ.get('GITHUB_ENV'):
            with open(os.environ['GITHUB_PATH'], 'a') as out:
                out.write(str(executable.parent) + '\n')
            with open(os.environ['GITHUB_ENV'], 'a') as out:
                out.write('VIDEOMATE_CI_RUNTIME=' + str(directory) + '\n')
        print('Prepared checksum-verified disposable Python/Tk ' + spec['version'] + ' for ' + tag)
        return directory
    except BaseException:
        shutil.rmtree(directory)
        raise


def cleanup_runtime():
    if not os.environ.get('VIDEOMATE_CI_RUNTIME'):
        return
    directory = Path(os.environ['VIDEOMATE_CI_RUNTIME']).resolve()
    parent = Path(os.environ['RUNNER_TEMP']).resolve()
    if directory.parent != parent or not directory.name.startswith('videomate-ci-python-'):
        raise ValueError('Refusing cleanup outside the exact job temporary directory')
    if (directory / '.videomate-ci-owned').read_text() != 'public-software-only\n':
        raise ValueError('Missing disposable CI ownership marker')
    shutil.rmtree(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    routing = commands.add_parser('matrix')
    routing.add_argument('--kind', choices=('tests', 'release'), required=True)
    routing.add_argument('--repo', choices=tuple(REPOS), required=True)
    routing.add_argument('--include-hosted', choices=('true', 'false'), default='false')
    runtime = commands.add_parser('runtime')
    runtime.add_argument('--python', choices=('3.11', '3.13'), required=True)
    runtime.add_argument('--parent', type=Path, default=os.environ.get('RUNNER_TEMP'))
    commands.add_parser('cleanup')
    args = parser.parse_args()
    if args.command == 'matrix':
        print('matrix=' + json.dumps(matrix(args.kind, args.repo, args.include_hosted == 'true'), separators=(',', ':')))
    elif args.command == 'runtime':
        if args.parent is None or not args.parent.is_dir():
            raise ValueError('An existing disposable job parent is required')
        prepare_runtime(args.python, args.parent)
    else:
        cleanup_runtime()


if __name__ == '__main__':
    main()
