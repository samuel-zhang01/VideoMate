# Manual local CI and platform coverage

The owner authorized dedicated local CI on 13 October 2026. Broad synthetic
checks and native packaging remain explicit manual checkpoints. None of the three
workflows run on pushes, pull requests or tags, and local jobs accept only the
owner repository on `main`. Runtime code and operator workflows are unchanged.

`Synthetic tests` defaults to Linux x86_64 and macOS ARM64 with both Python 3.11
and 3.13. The exact listener labels are `[deploy-vps, videomate]` and
`[local-macos, videomate]`. The matrix still defines Windows x86_64 and Linux ARM64
for both Python versions. They require the separate `include_hosted=true`
manual input, which can consume hosted minutes or incur charges. They are not
reported as tested when omitted. No untrusted PR runs use the owner's machines.

The job installs checksum-pinned relocatable Python/Tk into a newly created
job-temporary directory, then removes only that marked directory. Python 3.13
uses the existing runtime catalog; Python 3.11.16 uses official publisher asset
checksums from the same Astral release, 20260924. The provisioned runtime checks
its exact major/minor version and Tcl availability. No system interpreter,
owner application or security setting is installed or modified. Local Linux
uses the already-installed `xvfb-run`; it fails if that prerequisite is absent.
[Publisher distributions](https://github.com/astral-sh/python-build-standalone/releases/tag/20260924)
are public software, not test media.

All maintained tests are discovered unchanged. Python 3.13 additionally
provisions the existing checksum-pinned FFmpeg/FFprobe, enables the generated
native GUI/codec fixtures, checks the offline launcher and builds/smokes the
source zipapp. Python 3.11 retains the existing integration opt-in semantics;
ordinary mocked/privacy/recovery and available Tk tests still run. Tests make
fresh, exact temporary inputs and settings; no operator workspaces, filenames,
media, checkpoints or reports are discovered. The generated-media workflow keeps its Tk root withdrawn and forbids native
file pickers. Layout/journey tests use only dedicated generated windows; their
Mac suites share a synthetic-CI lock to prevent competing focus, and journey
fixtures establish focus in their own window and restore original Tk scaling.
The lock also covers native package self-tests across both repositories. The optional
external schema-reference test retains its existing dependency skip.

`Build release packages` also remains manual. Its default builds only the two
available local platforms. All four existing platform definitions and the
native source, runtime-kit and desktop gates remain. Draft creation requires
both explicit `include_hosted=true` and `create_draft=true`, after every platform
package passes, preventing a partial local build from creating a release.
Use a reviewed version tag containing the current CI helpers. No release build,
draft or owner installation is performed merely by publishing workflow edits.

Dispatch the synthetic checkpoint on `main` with `include_hosted=false` for
local proof. The resulting job labels, versions, full suite counts/skips and
platform identities are the coverage evidence; a workflow definition alone is
not a passed operating-system test. [Runner label semantics](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job).

`Native offline desktops` remains manual and defaults to the exact local Mac
listener. Its Windows platform definition and full source/native/offline gates
remain available only with `include_hosted=true`. Workflow routing edits do
not execute desktop packaging or create a release. The synthetic checkpoint
proves native source GUI/codec checks, not unexecuted bundled-package gates.
