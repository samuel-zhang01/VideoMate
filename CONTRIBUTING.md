# Contributing

Read `AGENTS.md` before working on VideoMate. Development and debugging use newly generated test media only. Never add operator media, paths, logs, mappings, keys, databases or diagnostic exports to Git or an issue.

The application uses Python 3.11+ and the standard library. Launch with `start.bat` (Windows) or `sh start.sh` (macOS/Linux). Missing pinned software is downloaded during setup; pass `--offline` to prohibit this. See `docs/launchers.md` for portable and offline installations.

## Local checks

Enable the source-only commit hook once per clone:

```sh
git config --local core.hooksPath .githooks
python tools/check_repository.py
```

The standalone guard and the commit hook read the Git index only. The hook also rejects known credential/private-key markers, credential URLs, personal home paths, and selected private narrative patterns; it prints only fixed category counts. It rejects non-source locations, symlinks, binary blobs and files over 1 MiB without printing rejected filenames, except the three exact allowlisted generated brand assets. `.gitignore` is a secondary safeguard; hooks are not access control. Stage named source files deliberately, never private directories.

Prefer focused checks for the changed behavior, for example `PYTHONPATH=src python -m unittest discover -s tests -p test_repository.py`. Run the broad suite only at an explicit checkpoint: `PYTHONPATH=src python -m unittest discover -s tests`. On PowerShell, use `$env:PYTHONPATH='src'`. Set `VIDEOMATE_TEST_GUI=1` in a graphical test session. Set `VIDEOMATE_TEST_FFMPEG` and `VIDEOMATE_TEST_FFPROBE` to the installed public tools for generated-media integration tests. These variables must never point to media. Linux CI uses Xvfb; native Windows/macOS use their local GUI session.

`python tools/gui_qa.py --size 800x600 --scale 2` opens a dedicated generated-fixture window. Do not open operator profiles or file pickers during assistant-led testing. `tools/gui_qa.py` removes its own temporary fixture when closed.

Update documentation and add tests for meaningful changes in privacy, recovery, installation or layout. Do not commit builds or downloaded dependencies. Dependency updates require new public URLs, reviewed SHA-256 pins, license review and platform tests. Keep `runtime-bootstrap.tsv` synchronized with `python-sources.json`; tests enforce equality.

VideoMate source is MIT-licensed; preserve the copyright and permission notice in `LICENSE`. Contributions must be your own work or include compatible provenance and notices. Third-party dependencies retain their own licenses; see `THIRD_PARTY_NOTICES.md`.

Native release builds use `python tools/build_release.py` on each matching architecture. Linux builds also produce an AppImage. The [release handoff](docs/release_development.md) lists the native gates and Apple Silicon plan. GitHub Actions stays disabled; do not dispatch it as part of a local build.

## Publication checks

`python tools/audit_public_release.py` checks staged source without enumerating working-tree runtime data. `--history` also checks locally reachable revisions and commit metadata; findings are category counts, never matched values. A zero result is a bounded scan, not proof that no unknown secret exists.

`python tools/prepare_public_release.py --output /local/new-public-source` creates a new, source-only Git repository from the reviewed index. It carries no old history, remote configuration, tags, release assets, or ignored files. The destination must be new. See [public release preparation](docs/public-release.md). Never publish the private development checkout by changing its visibility.
