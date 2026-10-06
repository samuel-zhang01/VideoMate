"""Desktop qualification using ONLY media generated inside a new temporary folder.

No user media path, workspace or job can be supplied to this routine.
The returned report contains fixed labels and booleans, never paths or raw logs.
"""
import hashlib
import json
import tempfile
import time
from pathlib import Path

from .dependencies import load_bundle, platform_tag
from .runner import Runner


def run_self_test():
    import tkinter as tk
    from .gui import Application
    report = {"schema_version": 1, "platform": platform_tag(), "synthetic_only": True, "checks": {}}
    root, app = None, None

    def require(condition, stage):
        if not condition:
            raise RuntimeError(stage)
        report["checks"][stage] = True

    def pump_until(predicate, seconds=90):
        deadline = time.monotonic() + seconds
        while not predicate():
            root.update()
            if time.monotonic() > deadline:
                raise RuntimeError("desktop_timeout")
            time.sleep(0.02)
        root.update()

    with tempfile.TemporaryDirectory(prefix="videomate-desktop-synthetic-") as temporary:
        scratch = Path(temporary).resolve()
        bundle = load_bundle()
        runner = Runner(timeout=30)
        source = scratch / "generated-fixture.avi"
        generated = runner.run([str(bundle.ffmpeg), "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                                "testsrc2=size=160x120:rate=25", "-t", "2", "-c:v", "mpeg4", "-g", "5", str(source)], scratch)
        require(generated.returncode == 0, "synthetic_generation")
        original = hashlib.sha256(source.read_bytes()).digest()
        try:
            from .gui_layout import create_root
            root = create_root()
            root.withdraw()
            app = Application(root, config_path=scratch / "settings.json", prepare_on_start=False)
            pump_until(lambda: app.backend_ready or (app.setup_worker and not app.setup_worker.is_alive() and app.events.empty()))
            require(app.backend_ready, "bundled_tools_and_encoders")
            app.workspace.set(str(scratch / "workspace"))
            app.start("scan")
            require(app.worker is None and not (scratch / "workspace").exists(), "gui_empty_queue_guard")
            app.add_input(str(source))
            require(app.sensitive.get() and app.files.item("0", "values")[0] == "Item 1", "gui_sensitive_names_hidden")
            app.recovered_dir.set(str(scratch / "custom-recovered"))
            app.diagnostics_dir.set(str(scratch / "custom-diagnostics"))
            app.logs_dir.set(str(scratch / "custom-logs"))
            app.write_logs.set(True)  # Sensitive must suppress logging even if configured.
            app.save_settings()
            from .preferences import load_preferences
            preferences = load_preferences(scratch / "settings.json")
            require(preferences.sensitive and preferences.recovered_dir == str(scratch / "custom-recovered"), "gui_settings_saved")

            def run(operation):
                app.log.configure(state="normal")
                app.log.delete("1.0", "end")
                app.log.configure(state="disabled")
                app.start(operation)
                require(app.worker is not None, "gui_worker_started")
                pump_until(lambda: not app.busy and app.events.empty())
                return app.log.get("1.0", "end")

            def run_generated_migration():
                from unittest.mock import patch

                prompts = []

                def confirm_session_only(title, _message, **_kwargs):
                    require(title == "Confirm interruption recovery", "gui_migration_expected_prompt")
                    prompts.append(title)
                    return True

                with patch("tkinter.messagebox.askyesno", side_effect=confirm_session_only):
                    log = run("run_workflow")
                require(prompts == ["Confirm interruption recovery"], "gui_migration_preflight_confirmed")
                return log

            require("no_errors_detected" in run("scan"), "gui_inspection")
            require((scratch / "workspace" / "jobs").is_dir(), "automatic_workspace")
            require(not any((scratch / "custom-diagnostics").iterdir()) and not any((scratch / "custom-logs").iterdir()), "sensitive_no_automatic_exports_or_logs")
            app.force.set(True)
            for strategy, profile, label in (("remux", "preserve_decoded_samples", "gui_remux"),
                                              ("reencode", "preserve_decoded_samples", "gui_lossless_reencode"),
                                              ("reencode", "compatible_sdr", "gui_compatible_reencode")):
                app.strategy.set(strategy)
                app.profile.set(profile)
                app.log.configure(state="normal")
                app.log.delete("1.0", "end")
                app.log.configure(state="disabled")
                require("verified_with_losses" in run("recover"), label)
            require(hashlib.sha256(source.read_bytes()).digest() == original, "original_preserved")

            # Deliberately erase one packet in this newly generated AVI.
            packets = runner.run([str(bundle.ffprobe), "-v", "error", "-select_streams", "v:0", "-show_packets",
                                  "-show_entries", "packet=pos,size", "-of", "json", str(source)], scratch)
            require(packets.returncode == 0, "synthetic_packet_selection")
            packet = json.loads(packets.stdout)["packets"][8]
            damaged = scratch / "generated-damage.avi"
            data = bytearray(source.read_bytes())
            position, size = int(packet["pos"]), int(packet["size"])
            data[position:position + size] = bytes(size)
            damaged.write_bytes(data)
            app.clear()
            app.add_input(str(damaged))
            app.strategy.set("auto")
            app.profile.set("preserve_decoded_samples")
            app.force.set(False)
            app.shorter.set(True)
            # This qualification step specifically exercises ordinary saved-job
            # resume. New Sensitive jobs otherwise have memory-only history.
            app.retain_history.set(True)
            app.log.configure(state="normal")
            app.log.delete("1.0", "end")
            app.log.configure(state="disabled")
            log = run("recover")
            require("verified_with_losses" in log and "damage_detected" in log, "gui_corrupt_packet_recovery")
            app.sensitive.set(False)  # A new-job preference must not downgrade this saved job.
            app.privacy_changed()
            require("Finished" in run("resume"), "gui_resume")
            require("input-1" in run("report"), "gui_grouped_report")
            require(not any((scratch / "custom-diagnostics").iterdir()) and not any((scratch / "custom-logs").iterdir()), "sensitive_resume_preserves_policy")
            run("export")
            exports = list((scratch / "custom-diagnostics").glob("*.log"))
            for export in exports:
                encoded = export.read_bytes()
                require(b"generated-fixture" not in encoded and b"generated-damage" not in encoded and
                        str(scratch).encode() not in encoded, "sanitized_exports")
            require(bool(exports), "gui_export")
            require(bool(exports) and all("Pipeline activity" in p.read_text(encoding="utf-8") for p in exports),
                    "gui_diagnostic_text_log")
            require(bool(list((scratch / "custom-recovered").glob("*/input-*/*"))), "custom_recovered_location")
            app.sensitive.set(False)
            app.privacy_changed()
            require(app.files.item("0", "values")[0] == str(damaged), "gui_sensitive_toggle_reveals_selection")
            require("damage_detected" in run("scan"), "gui_standard_inspection")
            require(bool(list((scratch / "custom-logs").glob("*.log"))), "configured_event_logs")
            require(damaged.read_bytes() == data, "damaged_original_preserved")
            collection = scratch / "generated-collection"
            nested = collection / "nested"
            nested.mkdir(parents=True)
            (nested / "healthy.avi").write_bytes(source.read_bytes())
            (nested / "damaged.avi").write_bytes(data)
            (collection / "notes.txt").write_bytes(b"Wholly synthetic migration note")
            app.clear()
            app.add_input(str(collection), "Folder")
            app.workflow.set("migrate")
            app.preset.set("Migrate — keep healthy formats")
            app.apply_profile()
            app.shorter.set(True)
            package = scratch / 'generated-migration-output-1'
            app.recovered_dir.set(str(package))
            log = run_generated_migration()
            require("Package status: complete" in log, "gui_migration_complete")
            require(package.is_dir() and package.with_name(package.name + '.status.json').is_file(), "gui_migration_one_package")
            require((package / "nested/healthy.avi").read_bytes() == source.read_bytes() and
                    (package / "notes.txt").read_bytes() == b"Wholly synthetic migration note",
                    "gui_migration_structure_and_verified_copies")
            require((package / "nested/damaged.mkv").is_file(), "gui_migration_verified_repair")
            require((nested / "damaged.avi").read_bytes() == data, "gui_migration_original_preserved")
            app.preset.set("Migrate — MP4 video")
            app.apply_profile()
            app.shorter.set(True)
            mp4_package = scratch / 'generated-migration-output-2'
            app.recovered_dir.set(str(mp4_package))
            log = run_generated_migration()
            require("Package status: complete" in log, "gui_mp4_migration_complete")
            require((mp4_package / "nested/healthy.mp4").is_file() and
                    (mp4_package / "nested/damaged.mp4").is_file(), "gui_mp4_migration_outputs")
            require("remux / none: succeeded" in log and "reencode /" in log,
                    "gui_mp4_copy_and_encode_fallback")
        finally:
            if app:
                app.cancel.set()
                if app.worker:
                    app.worker.join(timeout=45)
                if app.setup_worker:
                    app.setup_worker.join(timeout=45)
            if root:
                root.destroy()
    report["status"] = "passed"
    return report
