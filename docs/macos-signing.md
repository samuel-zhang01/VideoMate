# Apple Silicon signing and notarization

The native builder can produce a Developer ID signed app and, with an existing `notarytool` Keychain profile, a notarized DMG. This is a release-machine operation on the generated software package only. No media is an input, and the finished app still processes offline. The normal build remains ad-hoc signed for development.

## Prerequisites

- An active Apple Developer Program membership with an approved **Developer ID Application** certificate available to `codesign` on the release Mac. An Apple development or Mac App Store distribution certificate is not a substitute.
- A release bundle ID approved by the account holder and an existing `notarytool` Keychain profile. Credentials belong in Keychain or an approved signing service, never source, shell arguments, reports or this document.
- A reviewed source commit, native arm64 Mac, generated-fixture checks, license review and an output directory outside cloud sync. Never sign from an operator media directory.

## Account-holder setup

The account holder can complete these steps without sharing passwords, private keys, certificate requests, or account screenshots with the development team:

1. Confirm an active Apple Developer Program membership and Account Holder access. Apple requires that role to create a Developer ID Application certificate. If membership is absent, keep using the ad-hoc build for local development; it cannot be notarized as a Developer ID distribution.
2. Choose and approve a stable reverse-DNS bundle ID for VideoMate. Generate a certificate signing request in Keychain Access on the release Mac, create a **Developer ID Application** certificate in the Apple Developer account, and install the downloaded certificate into the same Keychain as its private key. See Apple's [Developer ID certificate](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/) and [certificate request](https://developer.apple.com/help/account/certificates/create-a-certificate-signing-request) guides.
3. Check that `security find-identity -v -p codesigning` shows the selected Developer ID Application identity locally. Its output contains account and team names; keep it local. The builder now checks the exact selected identity before provisioning or packaging and rejects a missing identity.
4. Create a `notarytool` Keychain profile on the release Mac, using an app-specific password or an approved App Store Connect API key. For the app-specific-password route, `xcrun notarytool store-credentials VideoMateNotary --apple-id APPLE_ACCOUNT --team-id TEAM_ID` prompts for the password. Do not put the password in command arguments or source. Apple's [notarytool guidance](https://developer.apple.com/documentation/technotes/tn3147-migrating-to-the-latest-notarization-tool) explains both authentication routes.

Do not start a signed release build until the account holder has approved the bundle ID and confirmed the local signing identity and notarization profile. The DMG gate also rejects an app signed by a different Apple team than the selected DMG identity.

Run from the source repository, replacing the placeholders with the account holder's approved values:

```sh
python3 tools/build_release.py \
  --output-root /local/non-synced/new-release-directory \
  --mac-sign-identity 'Developer ID Application: APPROVED TEAM NAME (TEAMID)' \
  --mac-bundle-id 'approved.example.videomate' \
  --mac-notary-profile 'approved-keychain-profile'
```

The builder refuses existing artifact names. PyInstaller signs collected Mach-O code with the selected identity and hardened runtime; the build then updates FFmpeg's trusted hashes, re-signs the outer app with a secure timestamp, verifies matching team identifiers, and reruns bundled and extracted generated-media self-tests. The DMG step rechecks the package manifest and ZIP hash, copies the signed app into a new image with an Applications shortcut, signs the image, submits it to Apple, staples the accepted ticket, and verifies the ticket and Gatekeeper assessment. Only a successful run writes a DMG checksum sidecar and fixed-field evidence JSON. It does not publish or upload the artifact anywhere except Apple's notarization service.

Omit `--mac-notary-profile` to build a Developer ID signed ZIP without submitting a DMG. A signed ZIP alone is not the Gatekeeper distribution artifact. Omit all Mac signing options for the existing ad-hoc development build. A rejected or interrupted notarization leaves its partial DMG for local review and does not create a checksum sidecar.

Before public release, test the downloaded DMG on a separate clean Apple Silicon Mac under Gatekeeper, including an offline launch without a system Python, then record the minimum tested macOS version and exact license/corresponding-source review. Do not publish the DMG from a working tree or treat a successful checksum as a substitute for those gates.
