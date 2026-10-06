"""Exact public document manifest shared by desktop and runtime packaging.

Do not discover arbitrary Markdown files in a checkout: private/local notes
may exist even when Git ignores them. Update this tuple with reviewed guides.
"""
DOCUMENTS = (
    "README.md", "LICENSE", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md",
    "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "archive/README.md", "dependencies/README.md",
    "docs/README.md",
    "docs/architecture.md", "docs/completed-jobs-and-retries.md", "docs/desktop.md",
    "docs/implementation-status.md", "docs/interruption-recovery.md", "docs/launchers.md",
    "docs/local-testing.md", "docs/macos-signing.md", "docs/migration-and-profiles.md",
    "docs/operator-testing.md", "docs/privacy-and-diagnostics.md", "docs/product-design.md",
    "docs/public-release.md", "docs/recovery-options.md", "docs/release-notes.md",
    "docs/release_development.md", "docs/releases.md", "docs/settings-and-privacy.md",
    "docs/validation-and-roadmap.md", "docs/development/validation.md",
    "docs/development/app-improvement-audit.md",
)


def source_documents(root):
    for name in DOCUMENTS:
        path = root / name
        parts = name.split("/")
        if any(root.joinpath(*parts[:depth]).is_symlink() for depth in range(1, len(parts) + 1)) or not path.is_file():
            raise ValueError("A reviewed release document is missing or linked.")
    return DOCUMENTS
