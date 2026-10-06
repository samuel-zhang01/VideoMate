# Public source preparation

The public deliverable is **source-only VideoMate 0.8.4 development preview**, with an MIT license and attribution to samuel-zhang01. Binary releases have separate native/platform, signing, and third-party source-material gates.

## Preparation completed

- Detailed installation, GUI, CLI, migration/resume, result, privacy, and troubleshooting README.
- Documentation index and a separate `docs/development/` area for curated synthetic-only evidence and the design audit.
- Removed operator-derived narrative and obsolete host-specific notes from the public source tree. Obsolete validation documents were replaced by a synthetic-only record.
- MIT license, package metadata, attribution guidance, updated contribution/security policy, and exact shared document manifests for desktop/runtime packaging.
- Offline redacted index/history audit and source-only snapshot builder. Neither discovers ignored data or publishes anything.
- Existing source-index guard extended only for the license and curated development documents. Excluded paths, symlinks, binaries, and oversized sources remain blocked.

## Audit boundary and findings

The 6 October 2026 review examined all **46 locally reachable commits** in a non-shallow checkout, including branches, remote-tracking refs, tags, and the four exact historical archived software/design paths. All seven advertised hosted branch/tag targets were already present in that local graph. It did not fetch unknown refs or inspect ignored/operator data. Git identities used a public GitHub noreply email. No personal home paths or credential-bearing remote URLs were detected.

Checksum-verified **Gitleaks 8.30.1** scanned that local history with full secret redaction and found no matching credentials. The additional source audit checks known credential formats, private-key markers, credential URLs, home paths, non-noreply commit emails, and selected operator-derived narrative patterns. These are bounded checks plus manual review, not a guarantee that every unknown secret or defect is absent.

The private development history contains documentation disclosures that must not become public. Editing/deleting current files leaves earlier revisions, tags, and release packages intact. Existing private release assets also need independent review; they are not part of this source-only deliverable. **Do not make the original development repository public or push its old refs to the publication repository.**

No operator media, settings, workspaces, checkpoints, private mappings, or diagnostic files were opened, copied, or cleaned. Publication tooling reads only approved Git source blobs. Exact branded project assets are the only permitted binary source files.

## Reproduce the source checks

Stage only reviewed source paths, then run:

```sh
python3 tools/check_repository.py
python3 tools/audit_public_release.py
python3 tools/audit_public_release.py --history
PYTHONPATH=src python3 -m unittest discover -s tests -p test_public_release.py
```

The history audit is expected to report findings in the **private development checkout**. Do not suppress those findings or interpret its nonzero exit as an application failure. The staged public source must pass. To scan credentials with an independently obtained, verified Gitleaks binary:

```sh
gitleaks git . --log-opts=--all --redact=100 --no-banner
```

First confirm every historical path is approved source; do not point a filesystem scanner at the checkout or private runtime directories. Gitleaks is optional developer tooling, not an application dependency. Retain any scan reports locally outside Git and do not publish matched values.

## Verification of this preparation

Focused local checks collected 22 tests: 21 passed and the optional external JSON-schema reference validator was skipped. Coverage includes source-index refusals, secret redaction/categories, exact single-commit snapshot trees, ignored-file/remote/history exclusion, document manifest coverage, release checksum gates, and the closed privacy/export schema. All 128 local Markdown links were checked against approved tracked paths, all staged Python source parsed, and eight README CLI examples parsed without executing input commands. No broad suite, product platform rebuild, or operator-data test was run.

## Create the publication repository

Choose a **new** non-synced local directory outside the checkout, with an existing parent:

```sh
python3 tools/prepare_public_release.py --output /local/new-videomate-public-source
```

The builder audits the staged index, copies exact Git blob bytes and modes, initializes a single-commit `main`, uses the existing public noreply identity, and verifies that its tree matches the reviewed index. It refuses existing destinations. It carries no old objects/history, tags, remote configuration, ignored files, release assets, or operator data. A later source edit requires another fresh snapshot; the tool does not overwrite old snapshots.

From that new directory, run the index/history checks and redacted Gitleaks scan again. Confirm one reachable commit, no remotes/tags, and a clean worktree. This new repository is the reviewable publication artifact. The original checkout/history stays private as the development record; it is not an archive to upload.

## Publication handoff

1. Review the prepared source snapshot and attribution. Authorize a **new public source repository** explicitly before creating/uploading it. Do not change the existing private repository's visibility as a shortcut.
2. Keep GitHub Actions disabled on the new repository before pushing. Retained workflow definitions accept manual dispatch only; enabling/dispatching them needs separate owner authorization. No self-hosted runner/service is installed.
3. Push only the new repository's reviewed `main`; never use `--mirror`, copy `.git`, or migrate old tags/releases/issues/attachments.
4. Set a concise description, topics, and private vulnerability reporting where supported. Verify the public commit tree and README/license render correctly. Do not publish review reports.
5. Keep old releases private. Build binaries only from a reviewed public-source commit on matching native hosts and complete [release gates](releases.md), [native build checks](release_development.md), and [third-party notices](../THIRD_PARTY_NOTICES.md).

No remote mutation, visibility change, upload, Actions run, binary rebuild, or history destruction is performed by this preparation. If reusing the original hosted repository later becomes necessary, it requires a separately reviewed removal plan for every branch/tag/release and host-retained commit view; a local rewrite alone is insufficient.
