# Third-party software

VideoMate launches FFmpeg and FFprobe as separate processes. Their licenses are independent of VideoMate's source code. VideoMate's own source is licensed under [MIT](LICENSE), copyright samuel-zhang01. Retain that attribution and permission notice in redistributed copies or substantial portions. This license does not replace any component license below.

| Component | Source and license information |
| --- | --- |
| FFmpeg / FFprobe | GPL-enabled builds; GPL notices retained in each tool bundle. Exact versions, URLs and SHA-256 pins: `dependencies/sources.json`. [FFmpeg source and licensing](https://ffmpeg.org/legal.html), [Gyan build source information](https://www.gyan.dev/ffmpeg/builds/), [BtbN build scripts](https://github.com/BtbN/FFmpeg-Builds), [Martin Riedl build scripts](https://git.martin-riedl.de/ffmpeg/build-script). |
| CPython / Tcl / Tk and runtime libraries | Runtime kits use the pinned Astral python-build-standalone distribution. Native desktops collect their native build interpreter and its license (GitHub builds use the Actions Python distribution). Desktop bundles also include the [Tcl](https://github.com/tcltk/tcl/blob/core-9-0-branch/license.terms) and [Tk](https://github.com/tcltk/tk/blob/core-9-0-branch/license.terms) license terms alongside the bundled libraries. [Runtime release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260924); exact platform archives in `dependencies/python-sources.json`. |
| PyInstaller and build helpers | Build-time tooling, pinned in `tools/requirements-build.txt`. Native desktops retain collected Python/PyInstaller notices and Tcl/Tk resources. [PyInstaller license and bootloader exception](https://pyinstaller.org/en/stable/license.html). |
| AppImage tooling | Linux release builds pin appimagetool and a type-2 runtime in `dependencies/appimage-sources.json`; these are build/distribution software, not media processors. [appimagetool](https://github.com/AppImage/appimagetool), [type-2 runtime](https://github.com/AppImage/type2-runtime). |

Keep licenses and notices with extracted packages. Checksums identify software; they are not publisher signatures. Redistribution must account for the exact bundled dependencies and corresponding-source requirements. Native development packages have not completed the public-distribution license/source-material gate. Source-only publication does not include the downloaded tools or interpreters. Before publishing a binary, include exact dependency license texts and provide/review the corresponding-source materials for its GPL-enabled FFmpeg build. Upstream links alone are not a completed package review.

## Source publication review

The 6 October 2026 source review did not identify copied third-party implementation code requiring an additional application-source license. The application uses Python standard-library modules and invokes separately installed processing tools. The included FFmpeg GPL and Tcl/Tk license texts retain their original notices. Project documentation identifies the raster mark as generated artwork, its SVG as hand-authored, and platform icons as derived project assets; no third-party brand reference is recorded. These observations are a bounded provenance review, not proof of exclusive rights or a formal legal clearance.

Other unrelated projects/products use the VideoMate name. This is samuel-zhang01's independent offline recovery project, with no claimed affiliation or exclusive trademark rights. Source publication does not grant rights to other parties' names or marks.
