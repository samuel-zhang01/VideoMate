"""Open a dedicated GUI containing ONLY a freshly generated damaged fixture.

For computer-use testing without opening file dialogs or operator workspaces.
Closing this exact window removes its test-owned temporary files.
"""
import json
import argparse
import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from videomate.dependencies import load_bundle
from videomate.gui import Application
from videomate.gui_layout import create_root
from videomate.runner import Runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', default=None, help='Test window geometry, e.g. 800x600')
    parser.add_argument('--scale', type=float, default=None, help='Test text scale, e.g. 1.5 for 150 percent')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="videomate-ui-generated-") as temporary:
        scratch = Path(temporary).resolve()
        bundle, runner = load_bundle(), Runner(timeout=30)
        source = scratch / "generated packet damage.avi"
        outcome = runner.run([str(bundle.ffmpeg), "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                              "testsrc2=size=160x120:rate=25", "-t", "3", "-c:v", "mpeg4", "-g", "5", str(source)], scratch)
        if outcome.returncode != 0:
            raise RuntimeError("Synthetic generation failed")
        packets = runner.run([str(bundle.ffprobe), "-v", "error", "-show_packets", "-show_entries", "packet=pos,size",
                              "-of", "json", str(source)], scratch)
        packet = json.loads(packets.stdout)["packets"][8]
        data = bytearray(source.read_bytes())
        offset, size = int(packet["pos"]), int(packet["size"])
        data[offset:offset+size] = bytes(size)
        source.write_bytes(data)
        root = create_root()
        if args.scale:
            root.tk.call('tk', 'scaling', args.scale * 96 / 72)
        app = Application(root, config_path=scratch / "settings.json", prepare_on_start=False)
        if args.size:
            root.geometry(args.size)
        root.title("VideoMate — synthetic UI QA " + str(os.getpid()))
        app.workspace.set(str(scratch / "workspace"))
        app.initialize()
        app.add_input(str(source))
        menu = tk.Menu(root)
        tests = tk.Menu(menu, tearoff=False)
        tests.add_command(label="Restore generated queue", command=lambda: app.add_input(str(source)))
        menu.add_cascade(label="Synthetic QA", menu=tests)
        root.configure(menu=menu)
        print(json.dumps({"window_title":root.title(), "pid":os.getpid(), "synthetic_only":True}), flush=True)
        root.mainloop()
        if source.read_bytes() != data:
            raise RuntimeError("Synthetic original changed")
        print("Computer-use session closed; synthetic original preserved.", flush=True)


if __name__ == "__main__":
    main()
