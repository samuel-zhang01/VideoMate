# Releases and maintenance

Publish the reviewed source-only snapshot described in [public release preparation](public-release.md). The original development repository stays private because its history and existing packages are outside the public snapshot. Commit source, tests, documentation and dependency catalogs. Binary archives belong in a separately qualified release, never Git history; private runtime data and operator media belong in neither.

## End-user setup

Recommend the complete native desktop ZIP where available. It includes Python/Tk and the processing tools. Existing runtime kits provide the same offline dependencies with shell launchers for their supported targets. Users do not need pip, Conda or a venv.

For source users, first launch checks for an explicit `VIDEOMATE_PYTHON`, an activated venv/Conda environment, a bundled local runtime or a suitable system Python. If Python/Tk needs downloading, setup explains the local installation and asks `[y/N]`. Declining leaves system software unchanged. Non-interactive setup requires `--yes`. Supplied/cached archives can be installed with `--offline` without a download prompt. Missing FFmpeg tools remain automatically provisioned unless offline mode is selected.

## Prepare a version

1. Update `src/videomate/__init__.py`, `pyproject.toml`, `CHANGELOG.md` and `docs/release-notes.md` together.
2. Test generated fixtures and setup paths, and document native platforms actually tested. Run `python tools/check_repository.py` before committing. Stage named source files.
3. On each native architecture run `python tools/build_release.py`. This provisions pinned public dependencies and build tools, creates a frozen desktop ZIP, and on Linux an AppImage. For a legacy runtime kit use `tools/build_zipapp.py` plus `tools/build_offline_bundle.py --include-runtime`. None of these builders use operator media. See [release development](release_development.md).
4. Execute the new package's generated-media self-test on its native platform. `tools/verify_kit.py ARCHIVE --execute` checks a runtime kit after extraction. Verify SHA-256 sidecars and include the exact tested-platform limitations in release notes.
5. Push the source commit, then create an immutable annotated `vX.Y.Z` tag. Create a GitHub **prerelease** manually with the tested archives and checksum sidecars. Do not upload untested foreign-platform binaries under a claim of native qualification, move a published tag, or overwrite release assets.

**GitHub Actions is disabled at the owner's request.** All retained workflows require explicit manual dispatch; release tags have no automatic trigger. Do not enable or dispatch them without new owner authorization. Self-hosted runner installation and signing credentials remain separate work. A local Windows/Linux preview can be released with an explicit platform limitation while Apple Silicon qualification is pending.

Authenticate Git/GitHub CLI using the platform credential manager. Never print, persist or commit credentials. Release assets are public software only; exclude operator diagnostics, runtime state and test media. Temporary generated fixtures are removed by their owning test; regression-test source remains in Git. Remove obsolete tracked material only by exact path after review; Git history retains it. Ignored local build archives and unrelated workspace contents are not part of a source cleanup.

VideoMate source is MIT-licensed with copyright attribution to samuel-zhang01. Third-party notices and corresponding-source obligations must be retained/reviewed before broader redistribution. Public visibility, signing, notarization and organization deployment approval are separate decisions.
