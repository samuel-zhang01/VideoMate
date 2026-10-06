"""Native offline desktop. No browser, server, previews or remote assets."""
import queue
import re
import threading
import time
import sys
from pathlib import Path

from . import __version__
from .gui_layout import ScrollSurface, create_root, flow_buttons, initial_geometry, wrap_to_parent
from .errors import VideoMateError
from .local_scan import report_local, resume_local, scan_local
from .recovery import PROFILES, RecoveryOptions
from .setup_local import check_backend, default_workspace, prepare_application
from .preferences import Preferences, default_config_path, load_preferences, save_preferences
from .progress import describe


class Application:
    BG, INK, MUTED, TEAL = "#f3f6f7", "#173542", "#526a75", "#087f83"
    RATE_LABELS = {"Auto — estimate from source": "auto", "Quality — software CRF": "quality",
                   "Approximate source file size": "source_size", "Target file size": "target_size", "Custom video bitrate": "bitrate"}
    LAYOUT_LABELS = {"Neutral names": "neutral", "Keep source filename": "filename", "Keep filename and folder structure": "folders"}
    UNRESOLVED_LABELS = {"Exclude from output; keep sources": "exclude", "Copy unchanged into output": "copy", "Copy to a separate review folder": "review"}
    LOUDNESS_LABELS = {"Off — leave audio level unchanged": "off", "Playback — target -16 LUFS": "playback", "Broadcast — target -23 LUFS": "broadcast"}
    HARDWARE_LABELS = {"Automatic — use optimized ranking": "auto", "Prefer NVIDIA (NVENC)": "nvidia",
                       "Prefer AMD (AMF)": "amd", "Prefer Intel (QSV)": "intel",
                       "Prefer Apple (VideoToolbox)": "apple"}

    def __init__(self, root, *, config_path=None, prepare_on_start=True):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.tk, self.ttk = root, tk, ttk
        self.inputs, self.controls, self.pages, self.navigation = [], [], {}, {}
        self.field_widgets, self.settings_forms = {}, {}
        self.events, self.cancel = queue.Queue(), threading.Event()
        self.worker, self.closing, self.backend_ready = None, False, False
        self.dependencies, self.setup_worker = None, None
        self._tools_recheck_pending = False
        self.finished_inputs = set()
        self.progress_state, self.progress_running = None, False
        self.completed_view = None
        self.action_only = False
        self.operation_pending = False
        self.retry_preview = None
        self.active_operation = None
        self.current_migration_checkpoint_ready = False
        self.private_retained_id = None
        self.applied_profile = None
        self.profile_baseline = None
        root.report_callback_exception = lambda *_: self.append(str(VideoMateError("internal_error")))
        root.title("VideoMate — Video integrity & recovery")
        if getattr(sys, "frozen", False):
            icon = Path(sys._MEIPASS) / "assets/videomate-mark.png"
        else:
            location = Path(__file__).absolute()
            archive = next((part for part in location.parents if part.suffix == ".pyz"), None)
            software_root = (archive.parent.parent if archive.parent.name == "dist" else archive.parent) if archive else location.parents[2]
            icon = software_root / "assets/videomate-mark.png"
        try:
            self.icon_image = tk.PhotoImage(file=str(icon))
            root.iconphoto(True, self.icon_image)
        except (OSError, tk.TclError):
            self.icon_image = None
        self.scale = max(0.75, root.winfo_fpixels("1i") / 96)
        width, height, min_width, min_height = initial_geometry(root.winfo_screenwidth(), root.winfo_screenheight(), self.scale)
        root.geometry(f"{width}x{height}")
        root.minsize(min_width, min_height)
        root.configure(bg=self.BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.configure_styles()
        selected_config = config_path if config_path is not None else default_config_path()
        settings_error = False
        try:
            preferences = load_preferences(selected_config)
        except VideoMateError:
            preferences, settings_error = Preferences(), True
        self.config_file = tk.StringVar(value=str(selected_config))
        self.sensitive, self.recursive = tk.BooleanVar(value=preferences.sensitive), tk.BooleanVar(value=preferences.recursive)
        self.force, self.shorter, self.drop_tracks = (tk.BooleanVar(value=value) for value in (preferences.force, preferences.allow_shorter, preferences.allow_track_loss))
        self.partial_salvage = tk.BooleanVar(value=preferences.partial_salvage)
        self.workspace = tk.StringVar(value=preferences.workspace or str(default_workspace()))
        self.recovered_dir, self.diagnostics_dir, self.logs_dir = (tk.StringVar(value=value) for value in (preferences.recovered_dir, preferences.diagnostics_dir, preferences.logs_dir))
        self.write_logs = tk.BooleanVar(value=preferences.write_logs)
        self.hardware_encoding = tk.BooleanVar(value=preferences.hardware_encoding)
        self.hardware_decoding = tk.BooleanVar(value=preferences.hardware_decoding)
        self.hardware_preference = tk.StringVar(value=next(k for k, v in self.HARDWARE_LABELS.items() if v == preferences.hardware_preference))
        self.hardware_calibration = dict(preferences.hardware_calibration)
        self.calibration_status = tk.StringVar(value="Select a codec, then optimize after your current job finishes.")
        self.diagnostic_logs = tk.BooleanVar(value=preferences.diagnostic_logs)
        self.reduce_motion = tk.BooleanVar(value=preferences.reduce_motion)
        self.cpu_threads = tk.StringVar(value=str(preferences.cpu_threads))
        self.max_runners = tk.StringVar(value=str(preferences.max_runners))
        self.migration_gpu_jobs = tk.StringVar(value=str(preferences.migration_gpu_jobs))
        self.migration_cpu_auto = tk.BooleanVar(value=preferences.migration_cpu_auto)
        self.migration_cpu_encoding = tk.BooleanVar(value=preferences.migration_cpu_encoding)
        self.max_source_percent = tk.StringVar(value=str(preferences.max_source_percent))
        self.size_tolerance_percent = tk.StringVar(value=str(preferences.size_tolerance_percent))
        self.audio_normalization = tk.StringVar(value=next(k for k, v in self.LOUDNESS_LABELS.items() if v == preferences.audio_normalization))
        self.audio_bitrate_kbps = tk.StringVar(value=str(preferences.audio_bitrate_kbps))
        self.software_preset = tk.StringVar(value=preferences.software_preset)
        self.mp4_faststart = tk.BooleanVar(value=preferences.mp4_faststart)
        self.custom_output = tk.BooleanVar(value=bool(preferences.recovered_dir))
        self.convert_all_mp4 = tk.BooleanVar(value=preferences.convert_all_mp4)
        self.convert_noncompliant_hevc = tk.BooleanVar(value=preferences.convert_noncompliant_hevc)
        self.video_codec = tk.StringVar(value=preferences.video_codec)
        self.rate_control = tk.StringVar(value=next(k for k, v in self.RATE_LABELS.items() if v == preferences.rate_control))
        self.output_layout = tk.StringVar(value=next(k for k, v in self.LAYOUT_LABELS.items() if v == preferences.output_layout))
        self.video_bitrate_kbps = tk.StringVar(value=str(preferences.video_bitrate_kbps))
        self.target_size_mib = tk.StringVar(value=str(preferences.target_size_mib))
        self.quality_crf = tk.StringVar(value=str(preferences.quality_crf))
        self.max_shorter_percent = tk.StringVar(value=str(preferences.max_shorter_percent))
        self.retain_history = tk.BooleanVar(value=preferences.retain_history)
        self.retain_mappings = tk.BooleanVar(value=preferences.retain_mappings)
        self.private_resume = tk.BooleanVar(value=preferences.private_resume)
        self.interruption_recovery = tk.BooleanVar(value=preferences.interruption_recovery)
        self.workflow = tk.StringVar(value=preferences.workflow)
        self.migration_local_names = tk.BooleanVar(value=preferences.migration_local_names)
        self.migration_preserve_times = tk.BooleanVar(value=preferences.migration_preserve_times)
        self.migration_unresolved = tk.StringVar(value=next(k for k, v in self.UNRESOLVED_LABELS.items() if v == preferences.migration_unresolved))
        self.custom_profiles = dict(preferences.profiles)
        self.preset = tk.StringVar(value="Choose a profile (optional)")
        self.size_policy = tk.StringVar(value=preferences.size_policy)
        self.profile_status = tk.StringVar(value="Custom settings")
        self.settings_state = tk.StringVar(value="Current session settings. Save to keep them after closing." if not settings_error else "Saved settings need review.")
        self.field_error = tk.StringVar()
        self.policy_text = tk.StringVar()
        self.conversion_hint = tk.StringVar()
        self.result_text = tk.StringVar(value="No completed job in this session.")
        self.result_policy = tk.StringVar()
        self.activity_note = tk.StringVar(value="Activity tail; results remain visible above. Scroll up to pause following.")
        self.advanced = tk.BooleanVar(value=False)
        self.workflow_hint = tk.StringVar()
        self.workflow_intro = tk.StringVar()
        self.timeout, self.max_output_mib = tk.StringVar(value=str(preferences.timeout)), tk.StringVar(value=str(preferences.max_output_mib))
        self.dependency_path = tk.StringVar(value=preferences.dependencies)
        self.dependencies = Path(preferences.dependencies) if preferences.dependencies else None
        self.strategy, self.profile = tk.StringVar(value=preferences.strategy), tk.StringVar(value=preferences.profile)
        self.input_kinds = []
        self.privacy_hint = tk.StringVar()
        self.job, self.status = tk.StringVar(), tk.StringVar(value="Choose a task and add your files." if not settings_error else "Saved settings could not be loaded. Review Settings before saving.")
        self.health = tk.StringVar(value="Checking processing tools…")
        self.storage_health = tk.StringVar(value="Settings and storage have not been prepared this session.")
        self.progress_text = tk.StringVar(value="Ready")
        self.selected_count, self.completed_count = tk.StringVar(value="0"), tk.StringVar(value="0")
        self.sidebar = sidebar = tk.Frame(root, bg="#102c38")
        self.brand = tk.Frame(sidebar, bg="#102c38")
        tk.Label(self.brand, text="▶", font=(self.font, 25), fg="#55d1c5", bg="#102c38").pack(anchor="w", pady=(0, 8))
        tk.Label(self.brand, text="VideoMate", font=(self.font, 22, "bold"), fg="white", bg="#102c38").pack(anchor="w")
        tk.Label(self.brand, text="VIDEO INTEGRITY", font=(self.font, 9), fg="#9bb8c3", bg="#102c38").pack(anchor="w", pady=(4, 0))
        self.navbar = tk.Frame(sidebar, bg="#102c38")
        for key, label in (("queue", "Start"), ("recovery", "Options"), ("jobs", "Activity"), ("setup", "Settings")):
            button = ttk.Button(self.navbar, text=label, style="Nav.TButton", command=lambda page=key: self.show(page))
            self.navigation[key] = button
        self.brand_note = tk.Label(sidebar, text="LOCAL BY DESIGN\n\nNo uploads. No telemetry.\nProcessing preserves originals.\n\nv" + __version__,
                 justify="left", font=(self.font, 10), fg="#acc7d0", bg="#102c38")
        self.body = body = ttk.Frame(root, padding=(24, 18, 24, 14))
        header = ttk.Frame(body)
        header.pack(fill="x")
        self.title_label = ttk.Label(header, text="Inspect. Repair. Migrate.", style="Title.TLabel")
        self.title_label.pack(side="left")
        self.badge = ttk.Label(header, text="LOCAL PROCESSING", style="Badge.TLabel", padding=(12, 7))
        self.subtitle = ttk.Label(body, text="Understand your videos. Recover what can be recovered.", style="Muted.TLabel")
        wrap_to_parent(self.subtitle)
        self.subtitle.pack(anchor="w", pady=(6, 12))
        consent = ttk.Frame(body, style="Notice.TFrame", padding=(12, 8))
        consent.pack(fill="x", pady=(0, 12))
        choices = ttk.Frame(consent, style="Notice.TFrame")
        choices.pack(fill="x")
        sensitivity_group = ttk.Frame(choices, style="Notice.TFrame")
        ttk.Label(sensitivity_group, text="Sensitive", background="#e5eef1", font=(self.font, 10, "bold")).pack(side="left", padx=(0, 12))
        for label, value in (("Yes", True), ("No", False)):
            self.register(ttk.Radiobutton(sensitivity_group, text=label, value=value, variable=self.sensitive,
                          command=self.privacy_changed, style="Privacy.TRadiobutton")).pack(side="left", padx=(0, 12))
        self.diagnostic_checkbox = self.register(ttk.Checkbutton(choices, text="Additional diagnostics", variable=self.diagnostic_logs,
            command=self.privacy_changed, style="Privacy.TCheckbutton"))
        flow_buttons(choices, [sensitivity_group, self.diagnostic_checkbox])
        self.privacy_hint_label = wrap_to_parent(ttk.Label(consent, textvariable=self.privacy_hint,
            background="#e5eef1", foreground=self.MUTED))
        self.privacy_hint_label.pack(anchor="w", pady=(3, 0))
        self.content = ttk.Frame(body)
        self.surfaces = {key: ScrollSurface(self.content, self.BG) for key in self.navigation}
        self.pages = {key: surface.frame for key, surface in self.surfaces.items()}
        self.queue_page(self.pages["queue"])
        self.recovery_page(self.pages["recovery"])
        self.jobs_page(self.pages["jobs"])
        self.setup_page(self.pages["setup"])
        def adapt_text(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, ttk.Label) and widget.cget("wraplength"):
                    wrap_to_parent(widget)
                adapt_text(widget)
        adapt_text(self.content)
        footer = ttk.Frame(body)
        footer.pack(side="bottom", fill="x", pady=(15, 0))
        self.progress_label = ttk.Label(footer, textvariable=self.progress_text, style="Muted.TLabel")
        wrap_to_parent(self.progress_label)
        self.progress_label.pack(fill="x", pady=(0, 5))
        self.progress = ttk.Progressbar(footer, mode="determinate", value=0, maximum=100, style="Teal.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 9))
        action_row = ttk.Frame(footer)
        action_row.pack(fill="x")
        self.cancel_button = ttk.Button(action_row, text="Stop job", command=self.stop_job, state="disabled")
        self.run_workflow_button = self.button(action_row, "Start inspection", lambda: self.start("run_workflow"), accent=True)
        flow_buttons(action_row, [self.run_workflow_button, self.cancel_button])
        status_label = ttk.Label(footer, textvariable=self.status, style="Muted.TLabel")
        wrap_to_parent(status_label)
        status_label.pack(fill="x", pady=(3, 0))
        self.job.trace_add("write", lambda *_: self.workflow_changed())
        self.private_resume.trace_add("write", lambda *_: self.update_resume_mode_hint())
        self.interruption_recovery.trace_add("write", lambda *_: self.update_resume_mode_hint())
        self.privacy_changed()
        self.content.pack(fill="both", expand=True)
        self.compact = None
        self.responsive_layout()
        root.bind("<Configure>", lambda event: self.responsive_layout() if event.widget is root else None, add="+")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind(sequence, self.scroll_page, add="+")
        self.show("queue")
        modifier = "Command" if root.tk.call("tk", "windowingsystem") == "aqua" else "Control"
        root.bind("<" + modifier + "-o>", lambda _: self.add_files() if not self.busy else None)
        self.poll_timer = root.after(100, self.poll)
        root.bind("<Destroy>", self.destroyed, add="+")
        self.check_tools()
        if prepare_on_start and not settings_error:
            self.initialize(startup=True)
        from .profiles import PROFILE_FIELDS
        for name in PROFILE_FIELDS:
            variable = getattr(self, {"allow_shorter": "shorter", "allow_track_loss": "drop_tracks"}.get(name, name))
            variable.trace_add("write", lambda *_: self.refresh_policy())
        self.refresh_policy()
        self.video_codec.trace_add("write", lambda *_: self.refresh_calibration_status())
        self.refresh_calibration_status()
        self._saved_settings = self.settings_snapshot()
        for variable in self.settings_variables().values():
            variable.trace_add("write", lambda *_: self.update_settings_state())
        root.bind("<" + modifier + "-s>", lambda _: self.save_settings() if not self.busy else None)

    def destroyed(self, event):
        if event.widget is self.root:
            self.cancel.set()
            if self.poll_timer:
                self.root.after_cancel(self.poll_timer)
                self.poll_timer = None

    @property
    def busy(self):
        return self.operation_pending or bool(self.worker and self.worker.is_alive())

    def configure_styles(self):
        import tkinter.font as tkfont
        self.font = tkfont.nametofont("TkDefaultFont").actual("family")
        style = self.ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=(self.font, 10), background=self.BG, foreground=self.INK)
        style.configure("TFrame", background=self.BG)
        style.configure("TLabel", background=self.BG)
        style.configure("Title.TLabel", font=(self.font, 23, "bold"))
        style.configure("Heading.TLabel", font=(self.font, 16, "bold"))
        style.configure("Muted.TLabel", foreground=self.MUTED)
        style.configure("Error.TLabel", foreground="#9c312a")
        style.configure("Badge.TLabel", foreground=self.TEAL, background="#e0eeee", font=(self.font, 9, "bold"))
        style.configure("Card.TFrame", background="white")
        style.configure("Card.TLabel", background="white")
        style.configure("Card.TCheckbutton", background="white", padding=(0, 5))
        style.configure("Number.TLabel", background="white", font=(self.font, 24, "bold"))
        style.configure("Notice.TFrame", background="#e5eef1")
        style.configure("Notice.TCheckbutton", background="#e5eef1")
        style.configure("Privacy.TRadiobutton", background="#e5eef1", padding=(8, 6))
        style.configure("TButton", padding=(13, 9), background="white", borderwidth=1, relief="flat")
        style.map("TButton", background=[("active", "#e4eff0")], foreground=[("disabled", "#859399")])
        style.configure("Accent.TButton", background=self.TEAL, foreground="white", borderwidth=0)
        style.map("Accent.TButton", background=[("disabled", "#8cabad"), ("active", "#056468")], foreground=[("disabled", "white")])
        style.configure("Nav.TButton", background="#102c38", foreground="#ccdde3", borderwidth=0, padding=(12, 10), anchor="w")
        style.map("Nav.TButton", background=[("pressed", "#087f83"), ("active", "#214653")], foreground=[("active", "white")])
        style.configure("Selected.Nav.TButton", background="#214653", foreground="white")
        style.map("Selected.Nav.TButton", background=[("pressed", "#087f83"), ("active", "#285667")], foreground=[("active", "white")])
        style.configure("Section.TButton", padding=(10, 7))
        style.configure("Selected.Section.TButton", background="#d5eaea", foreground=self.INK, padding=(10, 7))
        style.map("Selected.Section.TButton", background=[("active", "#c2e1df")])
        style.configure("TCheckbutton", padding=(0, 5))
        style.configure("Privacy.TCheckbutton", background="#e5eef1", padding=(0, 5))
        style.configure("TRadiobutton", padding=(0, 5))
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=round(36 * self.scale), borderwidth=0)
        style.configure("Treeview.Heading", background="#e5edf0", padding=(12, 9), font=(self.font, 10, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#d5eaea")], foreground=[("selected", self.INK)])
        style.configure("Teal.Horizontal.TProgressbar", background=self.TEAL, troughcolor="#dde7ea", borderwidth=0, thickness=4)

    def register(self, widget, state="normal"):
        self.controls.append((widget, state))
        try:
            variable = str(widget.cget("textvariable"))
            if variable:
                self.field_widgets[variable] = widget
        except self.tk.TclError:
            pass
        for surface in getattr(self, "surfaces", {}).values():
            if surface.contains(widget):
                widget.bind("<FocusIn>", surface.reveal, add="+")
                break
        return widget

    def button(self, parent, label, command, accent=False):
        return self.register(self.ttk.Button(parent, text=label, command=command, style="Accent.TButton" if accent else "TButton"))

    def check(self, parent, label, variable, **kwargs):
        widget = self.tk.Checkbutton(parent, text=label, variable=variable, anchor="w", justify="left",
            font=(self.font, 10), bg=self.BG, fg=self.INK, activebackground=self.BG,
            highlightthickness=1, highlightbackground=self.BG, highlightcolor=self.TEAL, **kwargs)
        return self.register(wrap_to_parent(widget, inset=44))

    def heading(self, parent, title, subtitle):
        self.ttk.Label(parent, text=title, style="Heading.TLabel").pack(anchor="w")
        wrap_to_parent(self.ttk.Label(parent, text=subtitle, style="Muted.TLabel")).pack(anchor="w", pady=(6, 15))

    def queue_page(self, page):
        # Reserve the actions before the flexible table, so a smaller window
        # shrinks the queue rather than clipping the repair or stop controls.
        bottom = self.ttk.Frame(page)
        bottom.pack(side="bottom", fill="x", pady=(9, 0))
        self.empty = self.ttk.Label(bottom, text="Select a source to get started.", style="Muted.TLabel")
        wrap_to_parent(self.empty).pack(anchor="w")
        self.recursive_option = self.check(bottom, "Include subfolders", self.recursive)
        self.recursive_option.pack(anchor="w", pady=(3, 5))
        actions = self.ttk.Frame(bottom)
        actions.pack(fill="x", pady=(4, 8))
        self.preview_workflow_button = self.button(actions, "Preview workflow", lambda: self.start("preview_workflow"))
        flow_buttons(actions, [self.preview_workflow_button,
            self.button(actions, "Options & profiles", lambda: self.show("recovery"))])
        wrap_to_parent(self.ttk.Label(bottom, textvariable=self.workflow_hint, style="Muted.TLabel")).pack(anchor="w")
        wrap_to_parent(self.ttk.Label(bottom, textvariable=self.health, style="Muted.TLabel")).pack(anchor="w", pady=(4, 0))
        self.stats = stats = self.ttk.Frame(page)
        stats.pack(fill="x", pady=(0, 18))
        for index, (label, value) in enumerate((("SELECTED ITEMS", self.selected_count), ("COMPLETED INPUTS", self.completed_count))):
            card = self.ttk.Frame(stats, style="Card.TFrame", padding=(18, 12))
            card.pack(side="left", fill="both", expand=True, padx=(0, 12))
            self.ttk.Label(card, text=label, style="Card.TLabel").pack(anchor="w")
            self.ttk.Label(card, textvariable=value, style="Number.TLabel").pack(anchor="w", pady=(5, 0))
        card = self.ttk.Frame(stats, style="Card.TFrame", padding=(18, 12))
        card.pack(side="left", fill="both", expand=True)
        self.ttk.Label(card, text="PROCESSING TOOLS", style="Card.TLabel").pack(anchor="w")
        self.ttk.Label(card, textvariable=self.health, style="Card.TLabel", wraplength=250).pack(anchor="w", pady=(12, 0))
        self.task_picker = self.ttk.Frame(page)
        self.task_picker.pack(fill="x", pady=(0, 12))
        self.ttk.Label(self.task_picker, text="1. Choose a task", style="Heading.TLabel").pack(anchor="w")
        task_buttons = self.ttk.Frame(self.task_picker)
        task_buttons.pack(fill="x", pady=(8, 0))
        flow_buttons(task_buttons, [self.register(self.ttk.Radiobutton(task_buttons, text=label, variable=self.workflow,
            value=value, command=self.workflow_changed)) for value, label in (("inspect", "Inspect"), ("repair", "Repair"), ("migrate", "Migrate a folder"))])
        wrap_to_parent(self.ttk.Label(self.task_picker, textvariable=self.workflow_intro,
            style="Muted.TLabel")).pack(fill="x", pady=(5, 0))
        self.migration_resume_card = self.ttk.Frame(page, style="Card.TFrame", padding=(14, 10))
        self.ttk.Label(self.migration_resume_card, text="If migration is interrupted", style="Card.TLabel",
                       font=(self.font, 12, "bold")).pack(anchor="w", pady=(0, 4))
        self.register(self.ttk.Checkbutton(self.migration_resume_card,
            text="Continue after Stop in this app",
            variable=self.interruption_recovery, style="Card.TCheckbutton")).pack(anchor="w", fill="x")
        self.register(self.ttk.Checkbutton(self.migration_resume_card,
            text="Also resume after closing",
            variable=self.private_resume, style="Card.TCheckbutton")).pack(anchor="w", fill="x")
        self.resume_mode_hint = self.tk.StringVar()
        wrap_to_parent(self.ttk.Label(self.migration_resume_card, textvariable=self.resume_mode_hint,
            style="Card.TLabel", foreground=self.MUTED)).pack(anchor="w", fill="x", pady=(4, 0))
        self.new_migration_button = self.button(self.migration_resume_card, 'Start a different migration…',
            lambda: self.start('run_workflow'))
        self.new_migration_hint = wrap_to_parent(self.ttk.Label(self.migration_resume_card,
            text='Use a new empty destination. Keep the current Job ID if you may return to its stopped package; its snapshot stays in this app.',
            style='Card.TLabel', foreground=self.MUTED))
        self.heading(page, "2. Select source", "Add videos to inspect or repair. Migration takes one folder and includes its subfolders and other files.")
        toolbar = self.ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 12))
        self.add_files_button = self.button(toolbar, "Add videos", self.add_files)
        self.add_folder_button = self.button(toolbar, "Add folder", self.add_folder)
        flow_buttons(toolbar, [self.add_files_button, self.add_folder_button,
            self.button(toolbar, "Remove selected", self.remove_selected), self.button(toolbar, "Clear", self.clear)])
        table = self.ttk.Frame(page)
        table.pack(fill="both", expand=True)
        self.files = self.ttk.Treeview(table, columns=("name", "kind"), show="headings", height=4, selectmode="extended")
        self.files.heading("name", text="Selected file or folder", anchor="w")
        self.files.heading("kind", text="Type", anchor="w")
        self.files.column("name", width=570, minwidth=120)
        self.files.column("kind", width=round(110 * self.scale), minwidth=80, stretch=False)
        scroll = self.ttk.Scrollbar(table, orient="vertical", command=self.files.yview)
        self.files.configure(yscrollcommand=scroll.set)
        self.files.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.destination_panel = self.ttk.Frame(page)
        self.destination_heading = self.ttk.Label(self.destination_panel, text="3. Save results", style="Heading.TLabel")
        self.destination_heading.pack(anchor="w", pady=(10, 6))
        self.output_toggle = self.check(self.destination_panel, "Use another output folder (optional)", self.custom_output, command=self.output_override_changed)
        self.output_toggle.pack(anchor="w")
        self.destination_controls = destination = self.ttk.Frame(self.destination_panel)
        self.register(self.ttk.Entry(destination, textvariable=self.recovered_dir)).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.button(destination, "Choose…", lambda: self.choose_location(self.recovered_dir)).pack(side="right")
        self.destination_hint = self.tk.StringVar()
        wrap_to_parent(self.ttk.Label(self.destination_panel, textvariable=self.destination_hint, style="Muted.TLabel")).pack(anchor="w", pady=(5, 8))
        self.recovered_dir.trace_add("write", lambda *_: self.output_location_changed())
        self.output_location_changed()
        self.migration_panel = self.ttk.Frame(page)
        wrap_to_parent(self.ttk.Label(self.migration_panel, text="A new migration needs an empty destination. For a stopped package, use Continue at the bottom of this window while the app stays open, or Activity > Resume from private checkpoint after restarting (only if enabled before the job).", style="Muted.TLabel")).pack(anchor="w", pady=(4, 8))
        self.button(self.migration_panel, "Resume after closing…", self.open_resume_activity).pack(anchor="w", pady=(0, 9))
        self.ttk.Label(self.migration_panel, text="If a video cannot be repaired", style="Muted.TLabel").pack(anchor="w", pady=(4, 5))
        self.register(self.ttk.Combobox(self.migration_panel, textvariable=self.migration_unresolved,
            values=list(self.UNRESOLVED_LABELS), state="readonly"), "readonly").pack(fill="x", pady=(0, 6))
        self.migration_names_option = self.check(self.migration_panel, "Permit original names in this local output (Sensitive)", self.migration_local_names)
        self.migration_names_option.pack(anchor="w", fill="x")
        self.migration_name_hint = self.tk.StringVar()
        wrap_to_parent(self.ttk.Label(self.migration_panel, textvariable=self.migration_name_hint, style="Muted.TLabel")).pack(anchor="w", pady=(4, 6))

    def recovery_page(self, page):
        self.heading(page, "Options & profiles", "Defaults are ready to use. Apply a saved profile or adjust recovery settings, then return to Start.")
        wrap_to_parent(self.ttk.Label(page, textvariable=self.field_error, style="Error.TLabel")).pack(fill="x", pady=(0, 6))
        self.button(page, "Back to Start", lambda: self.show("queue"), accent=True).pack(anchor="w", pady=(0, 10))
        self.ttk.Label(page, text="PROCESSING PROFILES", style="Muted.TLabel").pack(anchor="w", pady=(16, 5))
        from .profiles import builtins
        self.preset_choice = self.register(self.ttk.Combobox(page, textvariable=self.preset,
            values=[*builtins(), *self.custom_profiles], state="readonly"), "readonly")
        self.preset_choice.pack(fill="x")
        self.preset_choice.bind("<<ComboboxSelected>>", lambda _: self.apply_profile())
        wrap_to_parent(self.ttk.Label(page, textvariable=self.profile_status, style="Muted.TLabel")).pack(fill="x", pady=4)
        wrap_to_parent(self.ttk.Label(page, textvariable=self.policy_text)).pack(fill="x", pady=8)
        actions = self.ttk.Frame(page)
        actions.pack(fill="x", pady=(8, 10))
        flow_buttons(actions, [self.button(actions, "Save current as profile…", self.save_profile),
            self.button(actions, "Update saved profile", self.update_profile),
            self.button(actions, "Remove saved profile", self.remove_profile)])
        wrap_to_parent(self.ttk.Label(page, text="Choosing a profile applies it immediately. Profiles save processing options only; privacy and storage remain under your control.", style="Muted.TLabel")).pack(anchor="w")
        self.button(page, "Use source-size MP4 defaults", self.use_size_defaults).pack(anchor="w", pady=(8, 4))
        wrap_to_parent(self.ttk.Label(page, text="Copies healthy migration files unchanged. Automatic MP4 repair tries lossless stream copy first, then eligible encoding toward the source size with hardware preferred. Temporary size caps are off; encoding fallback is lossy.", style="Muted.TLabel")).pack(anchor="w", pady=(0, 6))
        self.check(page, "Preserve file timestamps during migration", self.migration_preserve_times).pack(anchor="w", fill="x")
        self.advanced_toggle = self.check(page, "Show advanced recovery options", self.advanced, command=self.workflow_changed)
        self.advanced_toggle.pack(anchor="w", pady=(16, 8))
        self.advanced_frame = self.ttk.Frame(page)
        page = self.advanced_frame
        self.heading(page, "Recovery tuning", "Applied to repairs and optional MP4 conversion. Healthy migration copies otherwise retain their original format and bytes.")
        self.check(page, "Convert every eligible file to MP4 — try stream copy, then verified re-encoding", self.convert_all_mp4,
                   command=lambda: self.convert_noncompliant_hevc.set(False) if self.convert_all_mp4.get() else None).pack(anchor="w", fill="x")
        self.check(page, "Selective HEVC migration — convert only non-MP4 or non-H.264/HEVC videos", self.convert_noncompliant_hevc,
                   command=lambda: self.convert_all_mp4.set(False) if self.convert_noncompliant_hevc.get() else None).pack(anchor="w", fill="x")
        wrap_to_parent(self.ttk.Label(page, textvariable=self.conversion_hint, style="Muted.TLabel")).pack(anchor="w", pady=(4, 8))
        self.ttk.Label(page, text="RECOVERY STRATEGY", style="Muted.TLabel").pack(anchor="w", pady=(4, 5))
        for value, label in (("auto", "Automatic — choose remux or re-encode from the findings"),
                             ("remux", "Remux only — rebuild the container without re-encoding"),
                             ("reencode", "Re-encode — decode and write a new video")):
            self.register(wrap_to_parent(self.tk.Radiobutton(page, text=label, variable=self.strategy, value=value,
                font=(self.font, 10), justify="left", anchor="w", bg=self.BG, activebackground=self.BG, fg=self.INK,
                highlightthickness=1, highlightbackground=self.BG, highlightcolor=self.TEAL), inset=44)).pack(anchor="w", fill="x", pady=3)
        self.ttk.Label(page, text="REPAIRED VIDEO FORMAT", style="Muted.TLabel").pack(anchor="w", pady=(16, 5))
        for value, label in (("preserve_decoded_samples", "Preserve decoded samples — FFV1 + PCM in MKV; larger files"),
                             ("compatible_sdr", "MP4 — compatible stream copy or selected video codec with AAC audio")):
            self.register(wrap_to_parent(self.tk.Radiobutton(page, text=label, variable=self.profile, value=value,
                font=(self.font, 10), justify="left", anchor="w", bg=self.BG, activebackground=self.BG, fg=self.INK,
                highlightthickness=1, highlightbackground=self.BG, highlightcolor=self.TEAL), inset=44)).pack(anchor="w", fill="x", pady=3)
        self.ttk.Label(page, text="MP4 QUALITY & SIZE", style="Muted.TLabel").pack(anchor="w", pady=(16, 5))
        wrap_to_parent(self.ttk.Label(page, text="Video codec for MP4 re-encoding", style="Muted.TLabel")).pack(anchor="w", pady=(0, 3))
        self.register(self.ttk.Combobox(page, textvariable=self.video_codec, values=("h264", "hevc"), state="readonly"), "readonly").pack(fill="x")
        wrap_to_parent(self.ttk.Label(page, text="h264 means H.264; hevc means H.265/HEVC. Both are video codecs. The MKV preservation format uses FFV1 instead.", style="Muted.TLabel")).pack(fill="x", pady=(4, 8))
        self.register(self.ttk.Combobox(page, textvariable=self.rate_control, values=list(self.RATE_LABELS), state="readonly"), "readonly").pack(fill="x")
        self.ttk.Label(page, text="Size policy: best_effort keeps verified outputs with a warning; strict withholds oversized outputs.", wraplength=700).pack(fill="x", pady=(8, 4))
        self.register(self.ttk.Combobox(page, textvariable=self.size_policy, values=("best_effort", "strict"), state="readonly"), "readonly").pack(fill="x")
        for label, variable in (("Custom video bitrate (kbit/s per video stream)", self.video_bitrate_kbps),
                                ("Target size per output (MiB; approximate)", self.target_size_mib),
                                ("Software quality CRF (0–51; lower = higher quality)", self.quality_crf),
                                ("Finished-size tolerance (% over target; default 25)", self.size_tolerance_percent),
                                ("Optional temporary cap (% of source; 0 = off)", self.max_source_percent),
                                ("Maximum duration loss when shorter output is allowed (%)", self.max_shorter_percent)):
            wrap_to_parent(self.ttk.Label(page, text=label)).pack(anchor="w", pady=(8, 3))
            self.register(self.ttk.Entry(page, textvariable=variable, width=14)).pack(anchor="w")
        wrap_to_parent(self.ttk.Label(page, text="Source/target size modes allow one bitrate-adjustment retry. Strict withholds outputs still above tolerance. Best effort keeps them only after full verification and records a size warning; unavailable estimates fall back to Auto. Smaller verified files are never padded. Temporary caps are separate; low-disk protection stays on.", style="Muted.TLabel")).pack(anchor="w", pady=(8, 5))
        self.ttk.Label(page, text="MP4 AUDIO & PLAYBACK", style="Muted.TLabel").pack(anchor="w", pady=(16, 5))
        self.register(self.ttk.Combobox(page, textvariable=self.audio_normalization, values=list(self.LOUDNESS_LABELS), state="readonly"), "readonly").pack(fill="x")
        wrap_to_parent(self.ttk.Label(page, text="Optional single-pass loudness normalization changes each audio track independently. It targets -1.5 dBTP and preserves sample rate/channels; it is not a certified loudness measurement. Choose Compatible SDR re-encoding. Healthy copies are unchanged unless Convert every eligible file is enabled.", style="Muted.TLabel")).pack(anchor="w", pady=(4, 8))
        for label, variable, values in (("AAC kbit/s per track (0 = adaptive)", self.audio_bitrate_kbps, (0, 64, 96, 128, 160, 192, 256, 320)),
                                        ("Software encoding speed (fast / medium / slow)", self.software_preset, ("fast", "medium", "slow"))):
            wrap_to_parent(self.ttk.Label(page, text=label)).pack(anchor="w", pady=(6, 3))
            self.register(self.ttk.Combobox(page, textvariable=variable, values=values, state="readonly"), "readonly").pack(fill="x")
        self.check(page, "MP4 fast-start — place the playback index at the beginning", self.mp4_faststart).pack(anchor="w", fill="x", pady=(8, 4))
        self.ttk.Label(page, text="OUTPUT ORGANIZATION", style="Muted.TLabel").pack(anchor="w", pady=(16, 5))
        self.layout_option = self.register(self.ttk.Combobox(page, textvariable=self.output_layout, values=list(self.LAYOUT_LABELS), state="readonly"), "readonly")
        self.layout_option.pack(fill="x")
        wrap_to_parent(self.ttk.Label(page, text="This control is for Repair with Sensitive: No. Migration always preserves filenames and relative folders; Sensitive migration separately asks permission for those local names. Originals are never overwritten.", style="Muted.TLabel")).pack(anchor="w", pady=(6, 4))
        self.ttk.Label(page, text="RECOVERY BEHAVIOR", style="Muted.TLabel").pack(anchor="w", pady=(16, 5))
        self.check(page, "Use available hardware encoding for Compatible SDR (software fallback)", self.hardware_encoding).pack(anchor="w")
        for label, variable in (("Convert files even when they pass inspection", self.force),
                                ("Accept shorter output when the source is incomplete", self.shorter),
                                ("Try one last verified partial recovery for damaged videos", self.partial_salvage),
                                ("Allow loss of subtitles, attachments and other auxiliary tracks", self.drop_tracks)):
            self.check(page, label, variable).pack(anchor="w")
        wrap_to_parent(self.ttk.Label(page, text="Partial recovery uses software decoding after other attempts fail. A playable shorter result is marked partial and the migration package needs review; originals remain untouched.", style="Muted.TLabel")).pack(anchor="w", pady=(4, 0))
        self.ttk.Label(page, text="Recovered files exclude metadata and chapters. Losses and possible decoder concealment are recorded.\nHDR and interlaced re-encoding require a supported policy and are currently blocked.",
                       style="Muted.TLabel", wraplength=730).pack(anchor="w", pady=(12, 0))
        self.ttk.Label(page, text="MANUAL ORIGINAL-FILE CLEANUP", style="Muted.TLabel").pack(anchor="w", pady=(20, 5))
        wrap_to_parent(self.ttk.Label(page, text="Select individual files on Start, then choose an action below. Unreadable does not mean irrecoverable. Cleanup is separate from repair and requires confirmation. Review-folder copies use neutral names and keep the media content.", style="Muted.TLabel")).pack(anchor="w", pady=(0, 8))
        cleanup = self.ttk.Frame(page)
        cleanup.pack(fill="x")
        flow_buttons(cleanup, [self.button(cleanup, "Move selected to review folder…", lambda: self.cleanup_selected("quarantine")),
                               self.button(cleanup, "Delete selected originals…", lambda: self.cleanup_selected("delete"))])

    def workflow_changed(self):
        workflow = self.workflow.get()
        previous_workflow = getattr(self, '_last_workflow', None)
        self._last_workflow = workflow
        if workflow == 'migrate' and previous_workflow != workflow:
            self._pending_resume_reveal = True
        self.update_resume_mode_hint()
        from .profiles import builtins
        self.preset_choice.configure(values=[k for k, v in {**builtins(), **self.custom_profiles}.items() if v.get("workflow", "inspect") == workflow])
        if hasattr(self, 'retry_button'):
            from .migration_resume import SESSION_RETRIES
            snapshot = SESSION_RETRIES.get(self.job.get()) if workflow == 'migrate' else None
            continuing = bool(snapshot and snapshot.get('mode') == 'continue')
            available = bool(snapshot) and not self.busy
            self.retry_preview_button.configure(state='normal' if available and not continuing else 'disabled')
            self.retry_button.configure(text='Continue stopped migration' if continuing else 'Start unresolved retry',
                state='normal' if available and (continuing or self.retry_preview) else 'disabled')
            self.resume_migration_button.configure(state='normal' if workflow == 'migrate' and self.job.get() and not snapshot and not self.busy else 'disabled')
            self.copy_job_button.configure(state='normal' if self.job.get() else 'disabled')
            if workflow == 'migrate' and continuing:
                self.resume_guidance.set('Stopped in this app session: reselect the same source and destination, keep the same recovery options, then click Continue stopped migration. No passphrase is needed.')
            elif workflow == 'migrate' and snapshot:
                self.resume_guidance.set('Completed with unresolved files: reselect the same source and destination, click Preview unresolved retry, then Start unresolved retry. This session snapshot ends when the app closes.')
            elif workflow == 'migrate' and self.job.get() and self.job.get() == self.private_retained_id:
                self.resume_guidance.set('This job retained a private checkpoint. Reselect the same source, destination and options, then resume with this Job ID and its original passphrase. Published outputs will be verified.')
            elif workflow == 'migrate':
                self.resume_guidance.set('Restart resume works only if a private checkpoint was enabled before this job. Reselect the same source, destination and options; enter the Job ID and original passphrase. This button checks the checkpoint; a log alone cannot resume.')
            else:
                self.resume_guidance.set('For a prior inspection or repair, enter its Job ID and use the matching restart control below. Private jobs need their original checkpoint and passphrase.')
            self.new_migration_button.pack_forget()
            self.new_migration_hint.pack_forget()
            if available and continuing:
                self.new_migration_button.pack(anchor='w', pady=(8, 4))
                self.new_migration_hint.pack(anchor='w')
        labels = {"inspect": "Start inspection", "repair": "Start repair", "migrate": "Start migration"}
        hints = {"inspect": "Inspect selected videos. No output copies are created.",
                 "repair": "Repair selected videos using the current profile; originals stay unchanged.",
                 "migrate": "Copy healthy videos and other files, repair what can be repaired, and report omissions. Originals stay unchanged."}
        primary_continue = workflow == 'migrate' and continuing and available
        self.run_workflow_button.configure(text="Continue stopped migration" if primary_continue else
            "Start new migration" if workflow == 'migrate' else labels[workflow],
            command=(lambda: self.start('continue_migration' if primary_continue else 'run_workflow')),
            state="normal" if self.backend_ready and not self.busy else "disabled")
        self.workflow_hint.set(hints[workflow])
        self.workflow_intro.set({
            "inspect": "Check whether selected videos can be read. Start here if you are unsure; inspection creates no recovered copies.",
            "repair": "Write independently verified recovered copies. The default preserves decoded samples in MKV and can create large files; choose a profile for MP4.",
            "migrate": "Build a new collection from one folder, including other file types. Choose an empty destination, then review what happens to unresolved videos."
        }[workflow])
        self.preview_workflow_button.configure(state="disabled" if workflow == "inspect" or self.busy else "normal")
        self.add_files_button.configure(state="disabled" if workflow == "migrate" or self.busy else "normal")
        self.add_folder_button.configure(text="Choose source folder" if workflow == "migrate" else "Add folder")
        self.files.configure(height=2 if workflow == 'migrate' else 4)
        self.add_folder_button.master.event_generate("<Configure>")
        self.recursive_option.configure(state="disabled" if workflow == "migrate" or self.busy else "normal")
        if workflow == "migrate":
            self.recursive.set(True)
        for widget in (getattr(self, "resume_option", None), getattr(self, "history_option", None)):
            if widget is not None:
                widget.configure(state="disabled" if self.busy or (workflow == "migrate" and widget is getattr(self, "history_option", None)) else "normal")
        self.migration_panel.pack_forget()
        self.migration_resume_card.pack_forget()
        if workflow == 'migrate':
            self.restart_controls_toggle.pack_forget()
            self.restart_controls_frame.pack_forget()
            self.migration_resume_actions.pack(fill='x', pady=(0, 12))
        else:
            self.migration_resume_actions.pack_forget()
            self.restart_controls_toggle.pack(fill='x', before=self.activity_log_heading, pady=4)
        self.migration_names_option.configure(state="normal" if self.sensitive.get() and not self.busy else "disabled")
        self.layout_option.configure(state="disabled" if workflow == "migrate" or self.sensitive.get() or self.busy else "readonly")
        self.destination_panel.pack_forget()
        if workflow != "inspect":
            self.destination_panel.pack(fill="x", pady=(6, 0))
        if workflow == "migrate":
            self.migration_resume_card.pack(fill="x", after=self.task_picker, pady=(0, 12))
            self.migration_panel.pack(fill="x", pady=(4, 8))
            self.destination_heading.configure(text="3. Choose destination")
            self.output_toggle.pack_forget()
            self.destination_hint.set("This folder itself holds the collection. A new job needs an empty folder. Blank uses Workspace/recovered. For an existing package, use Continue on Start or Resume on Activity.")
        else:
            self.destination_heading.configure(text="3. Save results")
            self.output_toggle.pack(anchor="w", after=self.destination_heading)
            self.destination_hint.set("Default: Workspace/recovered. Choose another folder only to store results elsewhere. This is the same output override shown in Settings.")
        self.output_location_changed()
        self.advanced_frame.pack_forget()
        if self.advanced.get() and workflow != "inspect":
            self.advanced_frame.pack(fill="x", pady=(4, 8))
        if workflow == 'migrate' and getattr(self, '_pending_resume_reveal', False):
            self.root.after_idle(self.reveal_migration_options)
        self.update_queue()
        if hasattr(self.run_workflow_button, "master"):
            self.run_workflow_button.master.event_generate("<Configure>")

    def update_resume_mode_hint(self):
        if not hasattr(self, 'resume_mode_hint'):
            return
        if self.private_resume.get():
            mode = 'Restart checkpoint selected. Before this NEW job, create and confirm a passphrase; keep it with the Job ID. The checkpoint authenticates data but does not encrypt it.'
            if not self.interruption_recovery.get():
                mode += ' Automatic reconnect is off in Settings.'
        elif self.interruption_recovery.get():
            mode = 'Session only. Disconnected storage can be retried; a stopped migration can continue while this app stays open. Closing loses its resume state.'
        else:
            mode = 'No interruption recovery selected. A stopped job cannot continue. Turn on one or both options above before starting.'
        self.resume_mode_hint.set(mode)

    def continue_or_retry(self):
        from .migration_resume import SESSION_RETRIES
        snapshot = SESSION_RETRIES.get(self.job.get())
        self.start('continue_migration' if snapshot and snapshot.get('mode') == 'continue' else 'retry_migration')

    def use_size_defaults(self):
        self.preset.set("Keep healthy · MP4 recovery" if self.workflow.get() == "migrate" else "Repair — compatible MP4")
        self.apply_profile()

    def refresh_policy(self):
        from .profiles import describe_policy, extract
        if getattr(self, '_refreshing_policy', False):
            return
        self._refreshing_policy = True
        try:
            self.conversion_hint.set(
                "Selective HEVC keeps healthy MP4 H.264/HEVC files unchanged. Other eligible videos use HEVC with AAC audio and playback loudness; every result is verified."
                if self.convert_noncompliant_hevc.get() else
                "MP4 conversion tries compatible stream copy first. Audio, quality or timing changes require re-encoding with the selected codec. Every result is verified."
                if self.convert_all_mp4.get() else
                "Healthy files keep their format unless conversion is selected. Repairs follow the format below; originals stay unchanged.")
            if self.convert_noncompliant_hevc.get():
                self.strategy.set('reencode')
                self.profile.set('compatible_sdr')
                self.video_codec.set('hevc')
                self.audio_normalization.set(next(k for k, v in self.LOUDNESS_LABELS.items() if v == 'playback'))
                self.rate_control.set(next(k for k, v in self.RATE_LABELS.items() if v == 'auto'))
            elif self.convert_all_mp4.get():
                self.strategy.set('auto')
                self.profile.set('compatible_sdr')
            for widget, normal in self.controls:
                variable = None
                # Radio/check buttons bind ``variable``; editable selectors
                # such as Combobox bind ``textvariable``. Both must reflect
                # preset-enforced values instead of allowing silent snap-back.
                for option in ('variable', 'textvariable'):
                    try:
                        variable = str(widget.cget(option))
                    except self.tk.TclError:
                        continue
                    if variable:
                        break
                if variable in {str(self.strategy), str(self.profile), str(self.video_codec), str(self.audio_normalization), str(self.rate_control)}:
                    locked = self.convert_noncompliant_hevc.get() or (self.convert_all_mp4.get() and variable in {str(self.strategy), str(self.profile)})
                    widget.configure(state='disabled' if locked or self.busy else normal)
            p = self.preferences()
            current = extract(p)
            self.policy_text.set(describe_policy(p))
            modified = current != self.profile_baseline
            self.profile_status.set((self.applied_profile + (" — modified" if modified else "")) if self.applied_profile else "Custom settings")
        except VideoMateError:
            self.policy_text.set("Some processing values need correction before starting.")
        finally:
            self._refreshing_policy = False

    def apply_profile(self):
        from .profiles import apply, PROFILE_FIELDS
        try:
            # Presets can restore invalid processing edits without changing
            # any current privacy/storage variables.
            from .profiles import extract
            try:
                current = self.preferences()
            except VideoMateError:
                current = Preferences(profiles=self.custom_profiles)
            preferences = apply(current, self.preset.get())
            aliases = {"allow_shorter": "shorter", "allow_track_loss": "drop_tracks"}
            self._refreshing_policy = True
            for name in PROFILE_FIELDS:
                variable = getattr(self, aliases.get(name, name))
                value = getattr(preferences, name)
                if name in {"rate_control", "output_layout", "migration_unresolved", "audio_normalization"}:
                    labels = {"rate_control": self.RATE_LABELS, "output_layout": self.LAYOUT_LABELS, "migration_unresolved": self.UNRESOLVED_LABELS, "audio_normalization": self.LOUDNESS_LABELS}[name]
                    value = next(k for k, v in labels.items() if v == value)
                variable.set(value)
            self._refreshing_policy = False
            self.workflow_changed()
            self.applied_profile = self.preset.get()
            self.profile_baseline = extract(self.preferences())
            self.refresh_policy()
            self.status.set("Processing profile applied. Privacy and storage settings stay under your control.")
        except VideoMateError as error:
            self._refreshing_policy = False
            self.report_settings_error(error)

    def save_profile(self):
        from tkinter import simpledialog
        from .profiles import builtins, extract, validate_profiles
        name = simpledialog.askstring("Save processing profile", "Choose a local profile name (up to 40 characters). Input selections and privacy permissions are excluded.", parent=self.root)
        if name is None:
            return
        try:
            name = name.strip()
            if name in builtins() or name in self.custom_profiles:
                self.status.set('That profile name already exists. Select it and use Update saved profile, or choose a new name.')
                return
            if len(self.custom_profiles) >= 12:
                self.status.set('Twelve custom profiles are already saved. Update or remove one before adding another.')
                return
            candidate = {**self.custom_profiles, name: extract(self.preferences())}
            validate_profiles(candidate)
            from dataclasses import replace
            save_preferences(self.selected_config_path(), replace(load_preferences(self.selected_config_path()), profiles=candidate))
            self.custom_profiles = candidate
            self.preset_choice.configure(values=[*builtins(), *candidate])
            self.preset.set(name)
            self.applied_profile = name
            self.profile_baseline = extract(self.preferences())
            self.refresh_policy()
            self.status.set("Processing profile saved locally.")
            self.workflow_changed()
        except VideoMateError as error:
            self.report_settings_error(error)

    def update_profile(self):
        from .profiles import extract, validate_profiles
        from dataclasses import replace
        name = self.preset.get()
        if name not in self.custom_profiles:
            self.status.set('Select a saved custom profile to update. Built-in recipes cannot be overwritten.')
            return
        try:
            candidate = {**self.custom_profiles, name: extract(self.preferences())}
            validate_profiles(candidate)
            path = self.selected_config_path()
            save_preferences(path, replace(load_preferences(path), profiles=candidate))
            self.custom_profiles = candidate
            self.applied_profile, self.profile_baseline = name, extract(self.preferences())
            self.refresh_policy()
            self.status.set('Saved profile updated. Other unsaved settings were not saved.')
            self.workflow_changed()
        except VideoMateError as error:
            self.report_settings_error(error)

    def remove_profile(self):
        from .profiles import builtins
        if self.preset.get() not in self.custom_profiles:
            self.status.set("Built-in profiles cannot be removed.")
            return
        try:
            from dataclasses import replace
            candidate = {k: v for k, v in self.custom_profiles.items() if k != self.preset.get()}
            save_preferences(self.selected_config_path(), replace(load_preferences(self.selected_config_path()), profiles=candidate))
            self.custom_profiles = candidate
            self.preset_choice.configure(values=[*builtins(), *candidate])
            self.preset.set("Choose a profile (optional)")
            self.applied_profile, self.profile_baseline = None, None
            self.refresh_policy()
            self.workflow_changed()
            self.status.set("Saved profile removed; current processing options are unchanged.")
        except VideoMateError as error:
            self.status.set(str(error))

    def jobs_page(self, page):
        self.heading(page, "Activity & findings", "Your Job ID and continuation options stay above the activity log.")
        wrap_to_parent(self.ttk.Label(page, textvariable=self.result_text)).pack(fill="x", pady=(0, 8))
        self.result_policy_label = wrap_to_parent(self.ttk.Label(page, textvariable=self.result_policy, style="Muted.TLabel"))
        self.result_policy_label.pack(fill="x", pady=(0, 8))
        resume_card = self.ttk.Frame(page, style='Card.TFrame', padding=(14, 10))
        resume_card.pack(fill='x', pady=(0, 10))
        self.ttk.Label(resume_card, text="JOB ID & CONTINUATION", style="Card.TLabel",
                       font=(self.font, 11, 'bold')).pack(anchor="w", pady=(0, 8))
        row = self.ttk.Frame(resume_card, style='Card.TFrame')
        row.pack(fill="x", pady=(0, 10))
        self.ttk.Label(row, text="Job ID", style='Card.TLabel').pack(side="left", padx=(0, 10))
        self.job_entry = self.register(self.ttk.Entry(row, textvariable=self.job))
        self.job_entry.pack(side="left", fill="x", expand=True)
        self.copy_job_button = self.ttk.Button(row, text='Copy ID', command=self.copy_job_id)
        self.copy_job_button.pack(side='left', padx=(8, 0))
        self.resume_guidance = self.tk.StringVar()
        wrap_to_parent(self.ttk.Label(resume_card, textvariable=self.resume_guidance,
            style='Card.TLabel', foreground=self.MUTED)).pack(fill='x', pady=(0, 8))
        actions = self.migration_resume_actions = self.ttk.Frame(resume_card, style='Card.TFrame')
        actions.pack(fill="x", pady=(0, 12))
        self.retry_preview_button = self.button(actions, 'Preview unresolved retry', lambda: self.start('preview_retry'))
        self.retry_button = self.button(actions, 'Start unresolved retry', self.continue_or_retry)
        self.resume_migration_button = self.button(actions, 'Resume from private checkpoint…', lambda: self.start('resume_migration'))
        flow_buttons(actions, [self.retry_preview_button, self.retry_button, self.resume_migration_button])
        restart = self.restart_controls_frame = self.ttk.Frame(page)
        show_restart = self.tk.BooleanVar(value=False)
        self.restart_controls_toggle = self.check(page, 'Show inspection/repair resume controls', show_restart,
            command=lambda: restart.pack(fill='x') if show_restart.get() and self.workflow.get() != 'migrate' else restart.pack_forget())
        self.restart_controls_toggle.pack(fill='x', pady=4)
        flow_buttons(restart, [self.button(restart, label, lambda op=op: self.start(op)) for label, op in
            (("Resume saved job", "resume"), ("Resume private scan", "resume_private_scan"), ("Resume private repair", "resume_private_recover"))])
        wrap_to_parent(self.ttk.Label(page, text="Resume verifies the selected source and published outputs before reuse. Keep the original options for Continue or private resume.", style='Muted.TLabel')).pack(fill='x', pady=4)
        export_actions = self.ttk.Frame(page)
        export_actions.pack(fill='x', pady=(0, 8))
        flow_buttons(export_actions, [self.button(export_actions, 'Review findings', lambda: self.start('report')),
            self.button(export_actions, 'Export diagnostic log', lambda: self.start('export'))])
        self.activity_log_heading = self.ttk.Label(page, text='ACTIVITY LOG', style='Muted.TLabel')
        self.activity_log_heading.pack(anchor='w', pady=(8, 5))
        wrap_to_parent(self.ttk.Label(page, textvariable=self.activity_note, style="Muted.TLabel")).pack(fill="x", pady=(0, 4))
        box = self.ttk.Frame(page)
        box.pack(fill="both", expand=True, pady=(0, 12))
        self.log = self.tk.Text(box, height=10, wrap="word", state="disabled", relief="flat", borderwidth=0,
                                bg="white", fg=self.INK, font=(self.font, 10), padx=14, pady=12, spacing3=5)
        scroll = self.ttk.Scrollbar(box, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        wrap_to_parent(self.ttk.Label(page, text="Export diagnostic log saves a detailed text log in the configured Diagnostics folder. Minimal-retention reports exist only in this session; export before closing. Exports do not contain a resumable checkpoint.", style="Muted.TLabel")).pack(anchor="w", pady=(0, 8))
        self.ttk.Label(page, text="Exports go to your diagnostics folder. Review them before sharing; keep job state and filename mappings private.",
                       style="Muted.TLabel", wraplength=750).pack(anchor="w", pady=(12, 0))

    def copy_job_id(self):
        identifier = self.job.get().strip()
        if not identifier:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(identifier)
        self.status.set('Job ID copied to the system clipboard. Treat it as private; restart also needs the original checkpoint and passphrase.')

    def setup_page(self, page):
        self.heading(page, "Settings", "Choose a section below. Changes apply to the next job; save them to keep them after closing.")
        actions = self.ttk.Frame(page)
        actions.pack(fill="x", pady=(0, 6))
        flow_buttons(actions, [self.button(actions, "Save settings", self.save_settings, accent=True),
                               self.button(actions, "Undo unsaved edits", self.revert_settings),
                               self.button(actions, "Reset session to defaults", self.reset_settings)])
        wrap_to_parent(self.ttk.Label(page, textvariable=self.settings_state, style="Muted.TLabel")).pack(fill="x", pady=(0, 6))
        wrap_to_parent(self.ttk.Label(page, textvariable=self.field_error, style="Error.TLabel")).pack(fill="x", pady=(0, 6))
        section_row = self.ttk.Frame(page)
        section_row.pack(fill="x", pady=(0, 12))
        sections = (("storage", "Storage"), ("privacy", "Privacy"), ("performance", "Performance"),
                    ("application", "Application"), ("display", "Display"))
        self.settings_navigation = {}
        for key, label in sections:
            self.settings_forms[key] = self.ttk.Frame(page)
            self.settings_navigation[key] = self.ttk.Button(section_row, text=label,
                command=lambda section=key: self.show_settings_section(section), style="Section.TButton")
        flow_buttons(section_row, list(self.settings_navigation.values()))
        self.settings_canvas = self.surfaces["setup"].canvas
        for title, rows in (("Storage", (("Workspace", self.workspace, "Jobs, private mappings and temporary candidates."),
                          ("Output location", self.recovered_dir, "Same setting as Start. Blank uses Workspace/recovered; a new migration requires the chosen folder to be empty."),
                          ("Diagnostics", self.diagnostics_dir, "Blank uses workspace/export-review."),
                          ("Event logs", self.logs_dir, "Blank uses workspace/logs. Sanitized codes, counts and optional technical diagnostics."))),
                            ("Application", (("Settings file", self.config_file, "Blank uses the default settings file. Use --config or VIDEOMATE_CONFIG to reopen a custom location."),
                          ("Processing tools", self.dependency_path, "Blank uses bundled FFmpeg and FFprobe.")))):
            form = self.settings_forms[title.lower()]
            self.ttk.Label(form, text=title, style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
            for label, variable, hint in rows:
                row = self.ttk.Frame(form, style="Card.TFrame", padding=(12, 9))
                row.pack(fill="x", pady=(0, 6))
                self.ttk.Label(row, text=label, style="Card.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
                entry = self.register(self.ttk.Entry(row, textvariable=variable))
                entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
                self.button(row, "Browse", lambda v=variable: self.choose_location(v)).grid(row=1, column=1)
                wrap_to_parent(self.ttk.Label(row, text=hint, style="Card.TLabel", foreground=self.MUTED)).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
                row.columnconfigure(0, weight=1)
        form = self.settings_forms["privacy"]
        self.heading(form, "Privacy & retention", "Sensitive controls names and retention. It does not encrypt files or isolate your operating system.")
        self.log_option = self.check(form, "Write event logs (Sensitive: No only)", self.write_logs)
        self.log_option.pack(anchor="w", pady=(10, 4))
        self.check(form, "Additional diagnostics: write safe technical logs (also for Sensitive jobs)", self.diagnostic_logs,
                   command=self.privacy_changed).pack(anchor="w", pady=(0, 4))
        self.ttk.Label(form, text="PRIVACY & RETENTION", style="Muted.TLabel").pack(anchor="w", pady=(14, 8))
        self.check(form, "Migration interruption recovery: reconnect verified storage and retry up to three times", self.interruption_recovery).pack(anchor="w", pady=(0, 4))
        self.resume_option = self.check(form, "Private resume: keep a keyed restart checkpoint (passphrase required)", self.private_resume)
        self.resume_option.pack(anchor="w")
        self.history_option = self.check(form, "Keep Sensitive Inspect/Repair history on disk, including source paths", self.retain_history)
        self.history_option.pack(anchor="w")
        self.mapping_option = self.check(form, "Keep export-to-filename mappings (Sensitive: No only)", self.retain_mappings)
        self.mapping_option.pack(anchor="w")
        wrap_to_parent(self.ttk.Label(form, text="Minimal retention uses an in-memory journal and removes session temporary candidates on exit. Private resume stores keyed content identifiers, sanitized results and neutral output tokens; its passphrase is not saved. Checkpoints authenticate data but do not encrypt technical details. Existing saved jobs/mappings are not erased.", style="Muted.TLabel")).pack(anchor="w", pady=(8, 0))
        form = self.settings_forms["performance"]
        self.heading(form, "Performance", "Automatic limits are a starting point. Hardware is checked before use; verification stays independent.")
        self.ttk.Label(form, text="ENCODING HARDWARE", style="Muted.TLabel").pack(anchor="w", pady=(14, 8))
        self.ttk.Label(form, text="GPU preference", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        self.register(self.ttk.Combobox(form, textvariable=self.hardware_preference,
            values=list(self.HARDWARE_LABELS), state="readonly"), "readonly").pack(fill="x", pady=(0, 8))
        self.optimize_button = self.button(form, "Optimize selected codec", self.optimize_hardware)
        self.optimize_button.pack(anchor="w", pady=(2, 4))
        wrap_to_parent(self.ttk.Label(form, textvariable=self.calibration_status, style="Muted.TLabel")).pack(anchor="w", pady=(0, 4))
        wrap_to_parent(self.ttk.Label(form, text="Optimization uses only generated 720p video, including a two-job check, and saves neutral route speeds with these local settings for 30 days. It runs for the codec selected in Options → Advanced recovery options, while idle. Every new job still checks that hardware works; CPU verification remains independent.", style="Muted.TLabel")).pack(anchor="w", pady=(0, 8))
        self.ttk.Label(form, text="PROCESSING LIMITS", style="Muted.TLabel").pack(anchor="w", pady=(14, 8))
        self.check(form, "Prefer hardware decoding for repair (integrity checks use software)", self.hardware_decoding).pack(anchor="w", pady=(0, 8))
        self.check(form, "Migration: automatically add a CPU encoding lane when enough logical CPUs are available", self.migration_cpu_auto).pack(anchor="w", pady=(0, 8))
        self.check(form, "Force CPU encoding lane when eligible, even below the automatic CPU threshold", self.migration_cpu_encoding).pack(anchor="w", pady=(0, 8))
        for label, variable in (("CPU thread budget (0 = available CPUs minus two)", self.cpu_threads),
                                ("Parallel files: Inspect / Migrate (0 = automatic)", self.max_runners),
                                ("Concurrent GPU jobs per qualified device (1–16)", self.migration_gpu_jobs),
                                ("Worker timeout (seconds)", self.timeout), ("Optional temporary size cap (MiB; 0 = off)", self.max_output_mib)):
            row = self.ttk.Frame(form)
            row.pack(fill="x", pady=4)
            wrap_to_parent(self.ttk.Label(row, text=label)).pack(anchor="w", pady=(0, 4))
            entry = self.register(self.ttk.Entry(row, textvariable=variable, width=14))
            entry.pack(side="left")
            if variable is self.cpu_threads:
                self.button(row, "Use all logical CPUs", self.use_all_cpu_threads).pack(side="left", padx=(8, 0))
        wrap_to_parent(self.ttk.Label(form, text="CPU thread counts are requests to FFmpeg, not dedicated cores. Full-CPU migration can be slower if encoding competes with GPU feeding, verification or disk reads.", style="Muted.TLabel")).pack(anchor="w", pady=(4, 0))
        wrap_to_parent(self.ttk.Label(form, text="Inspect/Migrate share the CPU budget. Automatic scheduling uses qualified hardware and available threads. Set parallel files to 1 for slow disks. Standalone Repair is serial.", style="Muted.TLabel")).pack(anchor="w", pady=(12, 0))
        form = self.settings_forms["application"]
        wrap_to_parent(self.ttk.Label(form, textvariable=self.health, style="Muted.TLabel")).pack(anchor="w", pady=(16, 8))
        row = self.ttk.Frame(form)
        row.pack(fill="x")
        flow_buttons(row, [self.button(row, "Check tools", self.check_tools), self.button(row, "Prepare workspace", self.initialize)])
        wrap_to_parent(self.ttk.Label(form, textvariable=self.storage_health, style="Muted.TLabel")).pack(anchor="w", pady=(8, 0))
        wrap_to_parent(self.ttk.Label(form, text="Prepare workspace creates missing app folders and saves current settings, including a missing settings file. It checks that the saved file can be read back.", style="Muted.TLabel")).pack(anchor="w", pady=(4, 0))
        form = self.settings_forms["display"]
        self.heading(form, "Display & motion", "Keep status readable while work runs in the background.")
        self.check(form, "Reduce motion — use a still indicator while progress is unknown", self.reduce_motion,
                   command=self.apply_motion_preference).pack(anchor="w", fill="x")
        wrap_to_parent(self.ttk.Label(form, text="File counts and status messages continue to update. Use Tab to move through controls; Command-S on macOS or Ctrl-S elsewhere saves settings.", style="Muted.TLabel")).pack(fill="x", pady=(8, 0))
        self.show_settings_section("storage")

    def show_settings_section(self, selected):
        for key, form in self.settings_forms.items():
            form.pack_forget()
            self.settings_navigation[key].configure(style="Selected.Section.TButton" if key == selected else "Section.TButton")
        self.settings_forms[selected].pack(fill="x", pady=(4, 8))
        self.settings_canvas.yview_moveto(0)

    def settings_variables(self):
        from dataclasses import fields
        aliases = {"allow_shorter": "shorter", "allow_track_loss": "drop_tracks", "dependencies": "dependency_path"}
        values = {field.name: getattr(self, aliases.get(field.name, field.name))
                  for field in fields(Preferences) if field.type is not dict}
        return {**values, "config_file": self.config_file}

    def settings_snapshot(self):
        from copy import deepcopy
        # Profiles are persisted by their own actions. Calibration can be cleared
        # by Reset and must participate in unsaved-state tracking.
        return tuple((key, variable.get()) for key, variable in self.settings_variables().items()) + (
            ("hardware_calibration", deepcopy(self.hardware_calibration)),)

    def update_settings_state(self):
        if not hasattr(self, "_saved_settings"):
            return
        dirty = self.settings_snapshot() != self._saved_settings
        self.settings_state.set("Unsaved changes — used for the next job. Save settings to keep them after closing."
                                if dirty else "No unsaved preference edits in this session.")

    def revert_settings(self):
        if self.busy:
            return
        from copy import deepcopy
        values = self.settings_variables()
        self._refreshing_policy = True
        try:
            for name, value in self._saved_settings:
                if name == "hardware_calibration":
                    self.hardware_calibration = deepcopy(value)
                else:
                    values[name].set(value)
        finally:
            self._refreshing_policy = False
        self.custom_output.set(bool(self.recovered_dir.get()))
        self.applied_profile, self.profile_baseline = None, None
        self.preset.set("Choose a profile (optional)")
        self.privacy_changed()
        self.refresh_policy()
        self.refresh_calibration_status()
        self.apply_motion_preference()
        self.field_error.set("")
        self.update_settings_state()
        self.status.set("Unsaved edits undone. Input selections and saved profiles are unchanged.")

    def report_settings_error(self, error):
        from .gui_validation import correction
        values = {key: variable.get() for key, variable in self.settings_variables().items()}
        issue = correction(values) if error.code in {"settings_invalid", "settings_location"} else None
        self.field_error.set(issue[1] if issue else str(error))
        self.status.set(self.field_error.get())
        if not issue:
            return
        widget = self.field_widgets.get(str(self.settings_variables()[issue[0]]))
        if widget is None:
            return
        for key, surface in self.surfaces.items():
            if surface.contains(widget):
                if key == "setup":
                    for section, form in self.settings_forms.items():
                        if str(widget).startswith(str(form) + "."):
                            self.show_settings_section(section)
                            break
                elif key == "recovery":
                    self.advanced.set(True)
                    # Corrections must remain reachable even with Inspect selected.
                    self.advanced_frame.pack(fill="x", pady=(4, 8))
                self.show(key)
                widget.focus_set()
                self.root.after_idle(lambda s=surface, w=widget: s.reveal(type("Focus", (), {"widget": w})()))
                break

    def apply_motion_preference(self):
        if self.progress_running and str(self.progress.cget("mode")) == "indeterminate":
            self.progress.stop()
            if not self.reduce_motion.get():
                self.progress.start(30)

    def stop_job(self):
        self.cancel.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("Stopping safely. Waiting for workers to exit; verified outputs remain.")

    def scroll_page(self, event):
        # Native text/table scrolling remains independent of the page surface.
        if isinstance(event.widget, (self.tk.Text, self.ttk.Treeview)):
            return
        for surface in self.surfaces.values():
            if surface.outer.winfo_ismapped() and surface.contains(event.widget):
                number, delta = getattr(event, "num", None), getattr(event, "delta", 0)
                if number not in (4, 5) and not delta:
                    return
                step = -1 if number == 4 or delta > 0 else 1
                surface.canvas.yview_scroll(step * max(1, int(abs(delta) / 120)), "units")
                return "break"

    def responsive_layout(self):
        width = self.root.winfo_width()
        if width < 10:
            width = int(self.root.geometry().split("x")[0])
        compact = width < round(1050 * self.scale)
        if self.compact == compact:
            return
        self.compact = compact
        for widget in (self.body, self.sidebar, self.brand, self.navbar, self.brand_note, self.badge):
            widget.pack_forget()
        for button in self.navigation.values():
            button.pack_forget()
        if compact:
            self.subtitle.pack_forget()
            self.title_label.pack_forget()
            self.privacy_hint_label.pack(anchor="w", pady=(3, 0))
            self.sidebar.pack(side="top", fill="x")
            self.navbar.pack(fill="x", padx=8, pady=5)
            for button in self.navigation.values():
                button.pack(side="left", fill="x", expand=True, padx=2)
            self.title_label.configure(font=(self.font, 18, "bold"))
            self.stats.pack_forget()
            self.body.configure(padding=(14, 10, 14, 10))
        else:
            self.title_label.pack(side='left')
            self.privacy_hint_label.pack(anchor='w', pady=(3, 0))
            self.subtitle.pack(anchor="w", pady=(6, 12), after=self.title_label.master)
            self.sidebar.pack(side="left", fill="y")
            self.brand.pack(anchor="w", padx=24, pady=(24, 28))
            self.navbar.pack(fill="x", padx=12)
            for button in self.navigation.values():
                button.pack(fill="x", pady=3)
            self.brand_note.pack(side="bottom", anchor="w", padx=24, pady=24)
            self.badge.pack(side="right")
            self.title_label.configure(font=(self.font, 23, "bold"))
            self.stats.pack(fill="x", pady=(0, 18), before=self.task_picker)
            self.body.configure(padding=(24, 18, 24, 14))
        self.body.pack(fill="both", expand=True)

    def choose_location(self, variable):
        from tkinter import filedialog
        chosen = (filedialog.asksaveasfilename(title="Choose settings file", defaultextension=".json", filetypes=(("JSON settings", "*.json"),))
                  if variable is self.config_file else filedialog.askdirectory(title="Choose local folder", mustexist=False))
        if chosen:
            variable.set(chosen)

    def output_location_changed(self):
        if self.recovered_dir.get():
            self.custom_output.set(True)
        if self.custom_output.get() or self.workflow.get() == 'migrate':
            self.destination_controls.pack(fill="x", pady=(4, 8))
        else:
            self.destination_controls.pack_forget()

    def output_override_changed(self):
        if not self.custom_output.get():
            self.recovered_dir.set("")
        self.output_location_changed()

    def preferences(self):
        try:
            return Preferences(sensitive=self.sensitive.get(), workspace=self.workspace.get(), recovered_dir=self.recovered_dir.get(),
                diagnostics_dir=self.diagnostics_dir.get(), logs_dir=self.logs_dir.get(), dependencies=self.dependency_path.get(),
                write_logs=self.write_logs.get(), reduce_motion=self.reduce_motion.get(), timeout=int(self.timeout.get()), max_output_mib=int(self.max_output_mib.get()),
                diagnostic_logs=self.diagnostic_logs.get(), cpu_threads=int(self.cpu_threads.get()),
                max_runners=int(self.max_runners.get()), hardware_decoding=self.hardware_decoding.get(),
                migration_gpu_jobs=int(self.migration_gpu_jobs.get()), max_source_percent=int(self.max_source_percent.get()),
                migration_cpu_auto=self.migration_cpu_auto.get(), migration_cpu_encoding=self.migration_cpu_encoding.get(),
                hardware_preference=self.HARDWARE_LABELS[self.hardware_preference.get()],
                hardware_calibration=dict(self.hardware_calibration),
                size_tolerance_percent=int(self.size_tolerance_percent.get()), audio_normalization=self.LOUDNESS_LABELS[self.audio_normalization.get()],
                size_policy=self.size_policy.get(),
                audio_bitrate_kbps=int(self.audio_bitrate_kbps.get()), software_preset=self.software_preset.get(), mp4_faststart=self.mp4_faststart.get(),
                convert_all_mp4=self.convert_all_mp4.get(), convert_noncompliant_hevc=self.convert_noncompliant_hevc.get(),
                video_codec=self.video_codec.get(), output_layout=self.LAYOUT_LABELS[self.output_layout.get()],
                rate_control=self.RATE_LABELS[self.rate_control.get()], video_bitrate_kbps=int(self.video_bitrate_kbps.get()),
                target_size_mib=int(self.target_size_mib.get()), quality_crf=int(self.quality_crf.get()), max_shorter_percent=int(self.max_shorter_percent.get()),
                retain_history=self.retain_history.get(), retain_mappings=self.retain_mappings.get(), private_resume=self.private_resume.get(), interruption_recovery=self.interruption_recovery.get(),
                workflow=self.workflow.get(), migration_local_names=self.migration_local_names.get(),
                migration_unresolved=self.UNRESOLVED_LABELS[self.migration_unresolved.get()],
                migration_preserve_times=self.migration_preserve_times.get(), profiles=dict(self.custom_profiles),
                recursive=self.recursive.get(), strategy=self.strategy.get(), profile=self.profile.get(), force=self.force.get(),
                allow_shorter=self.shorter.get(), partial_salvage=self.partial_salvage.get(),
                allow_track_loss=self.drop_tracks.get(), hardware_encoding=self.hardware_encoding.get()).validate()
        except (ValueError, KeyError, self.tk.TclError):
            raise VideoMateError("settings_invalid") from None

    def save_settings(self):
        if self.busy:
            return
        try:
            save_preferences(self.selected_config_path(), self.preferences())
            self._saved_settings = self.settings_snapshot()
            self.settings_state.set("Settings saved locally. Future sessions will use these values.")
            self.field_error.set("")
            self.status.set("Settings saved locally. Input selections are not saved.")
        except VideoMateError as error:
            self.report_settings_error(error)

    def selected_config_path(self):
        value = self.config_file.get()
        path = Path(value) if value.strip() else default_config_path()
        if not path.is_absolute():
            raise VideoMateError("settings_location")
        self.config_file.set(str(path))
        return path

    def check_migration_layout(self, preferences, config_path):
        if self.inputs:
            from .migration import validate_layout
            workspace = Path(preferences.workspace) if preferences.workspace else default_workspace()
            validate_layout(self.inputs, workspace,
                Path(preferences.recovered_dir) if preferences.recovered_dir else workspace / "recovered",
                Path(__file__).absolute().parents[2],
                excluded=[config_path, *(Path(p) for p in (preferences.diagnostics_dir, preferences.logs_dir) if p)])

    def reset_settings(self):
        self._refreshing_policy = True
        for variable, value in ((self.sensitive, True), (self.workspace, str(default_workspace())), (self.recovered_dir, ""),
                (self.diagnostics_dir, ""), (self.logs_dir, ""), (self.dependency_path, ""), (self.write_logs, False),
                (self.diagnostic_logs, False), (self.reduce_motion, False), (self.cpu_threads, "0"), (self.max_runners, "0"), (self.hardware_decoding, True),
                (self.migration_gpu_jobs, "2"), (self.migration_cpu_auto, True), (self.migration_cpu_encoding, False),
                (self.hardware_preference, "Automatic — use optimized ranking"),
                (self.max_source_percent, "0"), (self.custom_output, False),
                (self.size_policy, "strict"), (self.size_tolerance_percent, "25"), (self.audio_normalization, "Off — leave audio level unchanged"),
                (self.audio_bitrate_kbps, "0"), (self.software_preset, "medium"), (self.mp4_faststart, True),
                (self.convert_all_mp4, False), (self.convert_noncompliant_hevc, False), (self.video_codec, "h264"),
                (self.rate_control, "Auto — estimate from source"), (self.output_layout, "Neutral names"),
                (self.video_bitrate_kbps, "8000"), (self.target_size_mib, "500"), (self.quality_crf, "18"), (self.max_shorter_percent, "10"),
                (self.retain_history, False), (self.retain_mappings, False), (self.private_resume, False), (self.interruption_recovery, True),
                (self.workflow, "inspect"), (self.migration_local_names, False), (self.migration_preserve_times, True), (self.advanced, False),
                (self.migration_unresolved, "Exclude from output; keep sources"),
                (self.timeout, "3600"), (self.max_output_mib, "0"), (self.recursive, False), (self.strategy, "auto"),
                (self.profile, PROFILES[0]), (self.force, False), (self.shorter, False), (self.partial_salvage, True),
                (self.drop_tracks, False), (self.hardware_encoding, True)):
            variable.set(value)
        self._refreshing_policy = False
        self.hardware_calibration = {}
        self.refresh_calibration_status()
        self.applied_profile, self.profile_baseline = None, None
        self.preset.set('Choose a profile (optional)')
        self.refresh_policy()
        self.privacy_changed()
        self.output_location_changed()
        self.field_error.set("")
        self.update_settings_state()
        self.status.set("Defaults restored for this session. Save settings to keep them.")

    def use_all_cpu_threads(self):
        import os
        available = getattr(os, "process_cpu_count", os.cpu_count)() or 1
        self.cpu_threads.set(str(max(1, min(1024, available))))

    def privacy_changed(self):
        privacy = "Queue names hidden · Automatic exports off" if self.sensitive.get() else "Queue names visible · Automatic sanitized exports"
        self.privacy_hint.set(privacy + (" · Additional safe disk diagnostics on" if self.diagnostic_logs.get() else " · Additional diagnostics off"))
        self.log_option.configure(state="disabled" if self.sensitive.get() or self.busy else "normal")
        self.layout_option.configure(state="disabled" if self.sensitive.get() or self.busy else "readonly")
        self.mapping_option.configure(state="disabled" if self.sensitive.get() or self.busy else "normal")
        self.workflow_changed()
        self.update_queue()
        self.migration_names_option.configure(state="normal" if self.sensitive.get() and not self.busy else "disabled")
        self.migration_name_hint.set("Names and contents remain private. Start migration asks for permission if needed."
            if self.sensitive.get() else "Original filenames and folder structure are preserved automatically for migration.")

    def show(self, selected):
        for key, page in self.pages.items():
            self.surfaces[key].outer.pack_forget()
            self.navigation[key].configure(style="Selected.Nav.TButton" if key == selected else "Nav.TButton")
        self.surfaces[selected].outer.pack(fill="both", expand=True)
        if selected == 'queue' and getattr(self, '_pending_resume_reveal', False):
            self.root.after_idle(self.reveal_migration_options)

    def reveal_migration_options(self):
        if not getattr(self, '_pending_resume_reveal', False):
            return
        surface = self.surfaces['queue']
        if not surface.outer.winfo_ismapped():
            return
        self.root.update_idletasks()
        canvas, card = surface.canvas, self.migration_resume_card
        top = card.winfo_rooty() - canvas.winfo_rooty()
        bottom = top + card.winfo_height()
        if top < 0 or bottom > canvas.winfo_height():
            offset = canvas.canvasy(0) + top - 6
            canvas.yview_moveto(max(0, offset) / max(1, surface.frame.winfo_height()))
        self._pending_resume_reveal = False

    def open_resume_activity(self):
        self.show('jobs')
        self.root.update_idletasks()
        surface = self.surfaces['jobs']
        canvas = surface.canvas
        entry_top = self.job_entry.winfo_rooty() - canvas.winfo_rooty()
        if entry_top < 0 or entry_top + self.job_entry.winfo_height() > canvas.winfo_height():
            offset = canvas.canvasy(0) + entry_top - 12
            canvas.yview_moveto(max(0, offset) / max(1, surface.frame.winfo_height()))
        self.job_entry.focus_set()

    def check_tools(self):
        selected = Path(self.dependency_path.get()) if self.dependency_path.get() else None
        if self.setup_worker and self.setup_worker.is_alive():
            # A changed tools path must not inherit the readiness of a check
            # that was already running for the previous path.
            self._tools_recheck_pending = True
            self.backend_ready = False
            self.run_workflow_button.configure(state="disabled")
            self.health.set("Checking processing tools…")
            return
        self._tools_recheck_pending = False
        self.backend_ready = False
        self.run_workflow_button.configure(state="disabled")
        self.health.set("Checking processing tools…")
        self.dependencies = selected
        dependencies = self.dependencies
        def work():
            try:
                result = check_backend(dependencies)
                self.events.put(("backend", (dependencies, "FFmpeg " + result["version"] + " · Ready")))
            except Exception:
                self.events.put(("backend_error", (dependencies, "Tools unavailable — open Settings")))
        self.setup_worker = threading.Thread(target=work, name="videomate-setup", daemon=True)
        self.setup_worker.start()

    def refresh_calibration_status(self):
        record = self.hardware_calibration.get(self.video_codec.get())
        if not record:
            self.calibration_status.set("No saved optimization for this codec. Qualified default routes will be used.")
            return
        if record["expires_at"] <= time.time():
            self.calibration_status.set("Saved optimization expired. Run Optimize again when idle.")
            return
        routes = ", ".join(f"{item['id']}: {item['fps']:g} fps / {item['jobs']} job(s)" for item in record["routes"])
        self.calibration_status.set("Saved synthetic ranking — " + routes + ". Routes are rechecked for each job.")

    def optimize_hardware(self):
        if self.busy:
            self.status.set("Finish or stop the current job before optimizing hardware.")
            return
        if self.setup_worker and self.setup_worker.is_alive():
            self.status.set("Wait for the processing-tools check to finish.")
            return
        selected = Path(self.dependency_path.get()) if self.dependency_path.get() else None
        if selected != self.dependencies:
            self.check_tools()
            self.status.set("Wait for the selected processing tools to be checked.")
            return
        if not self.backend_ready:
            self.status.set("Processing tools are not ready. Check tools first.")
            return
        try:
            preferences, config_path = self.preferences(), self.selected_config_path()
        except VideoMateError as error:
            self.report_settings_error(error)
            return
        codec = preferences.video_codec
        dependencies = Path(preferences.dependencies) if preferences.dependencies else None
        workspace = Path(preferences.workspace) if preferences.workspace else default_workspace()
        self.cancel.clear()
        self.operation_pending = True
        for widget, _ in self.controls:
            widget.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.begin_progress()
        self.progress_text.set(f"Optimizing {codec.upper()} hardware… Stop job is available.")
        self.status.set(f"Optimizing {codec.upper()} with generated video. This may take a few minutes…")
        self.calibration_status.set("Measuring qualified routes; no source files are opened.")

        def work():
            try:
                from .calibration import optimize_generated
                from .dependencies import load_bundle
                from .execution import processing_session
                with processing_session(workspace):
                    record = optimize_generated(load_bundle(dependencies), codec, cancel_event=self.cancel)
                self.events.put(("calibration_ready", (codec, record, config_path)))
            except KeyboardInterrupt:
                self.events.put(("calibration_error", "Optimization stopped. Previous settings were kept."))
            except VideoMateError as error:
                message = ("Another job is using this workspace. Optimize after it finishes." if error.code == "job_busy"
                           else "No hardware route completed the synthetic check. Previous settings were kept.")
                self.events.put(("calibration_error", message))
            except OSError:
                self.events.put(("calibration_error", "Prepare the workspace, then try optimization again."))
            except Exception:
                self.events.put(("calibration_error", "Optimization could not finish. Previous settings were kept."))

        self.worker = threading.Thread(target=work, name="videomate-calibration", daemon=False)
        self.worker.start()

    def choose_dependencies(self):
        from tkinter import filedialog
        chosen = filedialog.askdirectory(title="Choose the ffmpeg folder containing your platform bundle")
        if chosen:
            self.dependency_path.set(chosen)
            self.dependencies = Path(chosen)
            self.check_tools()

    def choose_workspace(self):
        from tkinter import filedialog
        chosen = filedialog.askdirectory(title="Choose an existing VideoMate workspace")
        if chosen:
            self.workspace.set(chosen)

    def initialize(self, *, startup=False):
        try:
            preferences, config_path = self.preferences(), self.selected_config_path()
            if self.workflow.get() == "migrate":
                self.check_migration_layout(preferences, config_path)
            workspace = prepare_application(preferences, config_path, save_current=not startup)
            self.workspace.set(str(workspace))
            if not startup:
                self._saved_settings = self.settings_snapshot()
                self.settings_state.set("Settings saved and verified locally.")
            self.field_error.set("")
            self.storage_health.set("Settings file verified. Workspace and storage folders are ready.")
            self.status.set("Workspace ready. Choose a task and select your source." if startup else "Settings saved and verified. Workspace and storage folders ready.")
            return True
        except VideoMateError as error:
            self.report_settings_error(error)
        except OSError:
            self.status.set(str(VideoMateError("workspace_rejected")))
        self.storage_health.set("Preparation incomplete. " + self.status.get())
        return False

    def add_files(self):
        from tkinter import filedialog
        for file in filedialog.askopenfilenames(title="Select videos"):
            self.add_input(file, "Video file")

    def add_folder(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Select source folder", mustexist=True)
        if folder:
            if self.workflow.get() == "migrate":
                self.clear()
            self.add_input(folder, "Folder")
            self.recursive.set(True)

    def add_input(self, value, kind="Video file"):
        if value not in self.inputs:
            self.inputs.append(value)
            self.input_kinds.append(kind)
            self.update_queue()
            action = {"inspect": "inspection", "repair": "repair", "migrate": "migration"}[self.workflow.get()]
            self.status.set(f"{len(self.inputs)} selected. Click Start {action} to begin.")

    def update_queue(self):
        selected = set(self.files.selection())
        for item in self.files.get_children():
            self.files.delete(item)
        for index, (path, kind) in enumerate(zip(self.inputs, self.input_kinds)):
            self.files.insert("", "end", iid=str(index), values=(f"Item {index + 1}" if self.sensitive.get() else path, kind))
        self.files.selection_set([item for item in selected if self.files.exists(item)])
        self.selected_count.set(str(len(self.inputs)))
        empty_hint = "Choose one source folder above; all subfolders and file types are included." if self.workflow.get() == "migrate" else "Add videos or a folder above, then start " + ("inspection." if self.workflow.get() == "inspect" else "repair.")
        self.empty.configure(text=empty_hint if not self.inputs else
                             "Filenames are hidden. Sensitive applies to new jobs; saved jobs keep their setting." if self.sensitive.get() else
                             "Filenames stay local and are excluded from diagnostics.")

    def remove_selected(self):
        for index in sorted((int(item) for item in self.files.selection()), reverse=True):
            self.inputs.pop(index)
            self.input_kinds.pop(index)
        self.update_queue()

    def clear(self):
        self.inputs.clear()
        self.input_kinds.clear()
        for item in self.files.get_children():
            self.files.delete(item)
        self.update_queue()

    def append(self, message):
        following = self.log.yview()[1] >= 0.99
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 2000:
            self.log.delete("1.0", "500.0")
            self.activity_note.set("Older activity was removed from this bounded tail. Use Job summary or Export diagnostic log for grouped findings.")
        if following:
            self.log.see("end")
        self.log.configure(state="disabled")

    def start(self, operation):
        if self.busy:
            return
        interactive = operation == "run_workflow"
        continuing = operation == 'continue_migration'
        retry_id = self.job.get() if operation in {'preview_retry', 'retry_migration', 'continue_migration'} else None
        preview_retry = operation == 'preview_retry'
        if operation in {'preview_retry', 'retry_migration', 'continue_migration'} and not retry_id:
            self.status.set(str(VideoMateError('retry_session_unavailable')))
            return
        if retry_id:
            from .migration_resume import SESSION_RETRIES
            snapshot = SESSION_RETRIES.get(retry_id)
            if self.workflow.get() != 'migrate' or not snapshot or (continuing != (snapshot.get('mode') == 'continue')):
                self.status.set(str(VideoMateError('retry_session_unavailable')))
                return
            from dataclasses import asdict
            try:
                signature = (retry_id, asdict(self.preferences()), list(self.inputs))
            except VideoMateError as error:
                self.report_settings_error(error)
                return
            if not preview_retry and not continuing and signature != self.retry_preview:
                self.status.set('Options or selection changed. Preview unresolved retry before starting.')
                return
            operation = 'preview_migrate' if preview_retry else 'migrate'
        if operation in {"run_workflow", "preview_workflow"}:
            preview = operation == "preview_workflow"
            operation = {"inspect": "scan", "repair": "plan" if preview else "recover",
                         "migrate": "preview_migrate" if preview else "migrate"}[self.workflow.get()]
        private_identifier = None
        if operation in {"resume_private_scan", "resume_private_recover", "resume_migration"}:
            private_identifier = self.job.get()
            if not private_identifier:
                self.status.set("Enter the original private checkpoint Job ID on Activity, reselect the same source and destination, and restore the same recovery options.")
                return
            operation = {"resume_private_scan": "scan", "resume_private_recover": "recover", "resume_migration": "migrate"}[operation]
        selected_dependencies = Path(self.dependency_path.get()) if self.dependency_path.get() else None
        if operation not in {"report", "export"} and selected_dependencies != self.dependencies:
            self.check_tools()
        if operation not in {"report", "export"} and not self.backend_ready:
            self.status.set("Processing tools are not ready. Check Settings before starting.")
            self.show("setup")
            return
        if operation in {"scan", "plan", "recover", "migrate", "preview_migrate"} and not self.inputs:
            self.status.set("Add files or a folder before starting.")
            self.show("queue")
            if interactive:
                self.add_folder() if operation == "migrate" else self.add_files()
            return
        workspace, inputs, recursive, identifier = Path(self.workspace.get() or str(default_workspace())), list(self.inputs), self.recursive.get(), self.job.get()
        dependencies = self.dependencies
        try:
            config_path = self.selected_config_path()
            preferences = self.preferences() if operation in {"scan", "plan", "recover", "migrate", "preview_migrate"} else Preferences()
        except VideoMateError as error:
            self.report_settings_error(error)
            return
        self.field_error.set("")
        options = RecoveryOptions(strategy=self.strategy.get(), profile=self.profile.get(), force=self.force.get(),
                                  allow_shorter=self.shorter.get(), partial_salvage=self.partial_salvage.get(),
                                  allow_track_loss=self.drop_tracks.get(),
                                  max_output_bytes=preferences.max_output_mib * 1024 ** 2, hardware_encoding=preferences.hardware_encoding,
                                  convert_all_mp4=preferences.convert_all_mp4, convert_noncompliant_hevc=preferences.convert_noncompliant_hevc,
                                  video_codec=preferences.video_codec, rate_control=preferences.rate_control,
                                  video_bitrate_kbps=preferences.video_bitrate_kbps, target_size_mib=preferences.target_size_mib,
                                  quality_crf=preferences.quality_crf, max_shorter_percent=preferences.max_shorter_percent,
                                  max_source_percent=preferences.max_source_percent, size_tolerance_percent=preferences.size_tolerance_percent,
                                  size_policy=preferences.size_policy,
                                  audio_normalization=preferences.audio_normalization, audio_bitrate_kbps=preferences.audio_bitrate_kbps,
                                  software_preset=preferences.software_preset, mp4_faststart=preferences.mp4_faststart)
        if operation in {"migrate", "preview_migrate"}:
            if len(inputs) != 1 or self.input_kinds != ["Folder"]:
                self.status.set("Migration needs one source folder. Choose source folder to replace the current selection.")
                self.show("queue")
                if interactive:
                    self.add_folder()
                return
            try:
                self.check_migration_layout(preferences, config_path)
            except VideoMateError as error:
                self.status.set(str(error))
                self.show("queue")
                return
            if operation == "migrate" and preferences.sensitive and not preferences.migration_local_names:
                from tkinter import messagebox
                if not messagebox.askyesno("Allow names in the local output?",
                        "Migration preserves original filenames and folders in the new local output.\n\n"
                        "The output remains sensitive. Diagnostics still exclude names and paths. Originals will not be changed.\n\n"
                        "Allow this and start migration?", parent=self.root, default="no"):
                    self.status.set("Migration not started. Local filename permission was declined.")
                    return
                from dataclasses import replace
                self.migration_local_names.set(True)
                preferences = replace(preferences, migration_local_names=True)
        use_private_resume = not retry_id and operation in {"scan", "recover", "migrate"} and ((preferences.private_resume and (preferences.sensitive or operation == "migrate")) or private_identifier is not None)
        if operation == 'migrate' and not retry_id and not private_identifier and not use_private_resume:
            from tkinter import messagebox
            warning = ("This migration can continue after Stop only while VideoMate stays open. "
                       "Closing the app loses its session-only resume state.\n\n"
                       "To resume after closing, cancel and select the private checkpoint option on Start before this job begins.\n\n"
                       "Start with session-only recovery?") if preferences.interruption_recovery else (
                       "Interruption recovery is off. A stopped job cannot continue after Stop or closing.\n\n"
                       "Cancel and turn it on before starting, or start without recovery?")
            if not messagebox.askyesno('Confirm interruption recovery', warning, parent=self.root, default='no'):
                self.status.set('Migration not started. Choose interruption recovery on Start, then try again.')
                self.show('queue')
                return
        passphrase = None
        if use_private_resume:
            if not preferences.sensitive and operation != "migrate":
                self.status.set("Private resume is available with Sensitive: Yes. Ordinary jobs use saved-job resume.")
                return
            from tkinter import simpledialog
            prompt = ("Enter the original checkpoint passphrase. VideoMate does not save it." if private_identifier else
                      "Create a passphrase (at least 12 characters) for this job. Keep it with the Job ID; VideoMate does not save it.")
            passphrase = simpledialog.askstring("Private resume", prompt, show="*", parent=self.root)
            if passphrase is None:
                return
            if not 12 <= len(passphrase) <= 1024:
                self.status.set(str(VideoMateError("passphrase_required")))
                return
            if not private_identifier:
                repeat = simpledialog.askstring('Confirm private resume passphrase',
                    'Enter the same passphrase again. Neither entry is saved by VideoMate.',
                    show='*', parent=self.root)
                if repeat is None:
                    return
                if repeat != passphrase:
                    self.status.set('Passphrases did not match. Nothing started; enter and confirm a new passphrase.')
                    return
        self.cancel.clear()
        self.active_operation = operation
        self.current_migration_checkpoint_ready = False
        self.operation_pending = True
        self.action_only = operation in {"report", "export", "preview_migrate", "plan"}
        if not self.action_only:
            self.finished_inputs.clear()
            self.completed_view = None
            new_job = operation in {'scan', 'recover', 'migrate'} and not (retry_id or private_identifier)
            if new_job:
                self.job.set("")
            self.completed_count.set("0")
            from .profiles import describe_policy
            self.result_policy.set(("Retry policy (retried inputs only): " if retry_id else "Job policy: ") + describe_policy(preferences))
            self.result_text.set("Job running; outcome pending.")
            self.retry_preview = None
        for widget, _ in self.controls:
            widget.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        if not self.action_only:
            self.begin_progress()
        self.append("— " + {"report": "Review findings", "export": "Diagnostic export", "preview_migrate": "Migration preview", "plan": "Repair preview"}.get(operation, "Processing job") + " —")
        self.status.set("Working locally. Detailed findings appear below.")
        self.show("jobs")
        def work():
            reported_id = None
            private_retained = False
            def emit(message):
                nonlocal reported_id, private_retained
                if message.startswith("Job: "):
                    reported_id = message[5:]
                if message.startswith('Migration restart checkpoint enabled.'):
                    self.events.put(('checkpoint_ready', True))
                if message.startswith('Private restart checkpoint retained.'):
                    private_retained = True
                    self.events.put(('private_retained', reported_id))
                if message.startswith('Private restart checkpoint removed after complete package.'):
                    self.events.put(('private_checkpoint_removed', reported_id))
                self.events.put(("message", message))
            def finish(message, *, outcome=True):
                if not self.action_only and not reported_id and identifier:
                    self.events.put(('restore_job_id', identifier))
                if not self.action_only and reported_id:
                    from .private_state import LIVE_REPORTS
                    from .result_summary import summarize
                    if reported_id in LIVE_REPORTS:
                        try:
                            view = summarize(LIVE_REPORTS[reported_id][2])
                            self.events.put(("result_view", view))
                            if outcome:
                                message = view['title']
                        except VideoMateError:
                            emit('Result summary unavailable [invalid_export]. The processing outcome below is unchanged.')
                self.events.put(("done", message))
            try:
                if operation == "resume":
                    code = resume_local(identifier, workspace, dependencies=dependencies, emit=emit, cancel_event=self.cancel)
                elif operation in {"report", "export"}:
                    code = report_local(identifier, workspace, export=operation == "export", emit=emit)
                elif operation in {"migrate", "preview_migrate"}:
                    from .migration import migrate_local
                    prepare_application(preferences, config_path)
                    code = migrate_local(inputs, workspace, dependencies=dependencies, recovery=options,
                        execute=operation == "migrate", sensitive=preferences.sensitive,
                        local_names=preferences.migration_local_names, preserve_file_times=preferences.migration_preserve_times,
                        unresolved=preferences.migration_unresolved,
                        package_layout='direct',
                        recovered_dir=preferences.recovered_dir, diagnostics_dir=preferences.diagnostics_dir,
                        logs_dir=preferences.logs_dir, write_logs=preferences.write_logs, diagnostic_logs=preferences.diagnostic_logs,
                        cpu_threads=preferences.cpu_threads, max_runners=preferences.max_runners,
                        migration_gpu_jobs=preferences.migration_gpu_jobs,
                        migration_cpu_auto=preferences.migration_cpu_auto,
                        migration_cpu_encoding=preferences.migration_cpu_encoding,
                        hardware_preference=preferences.hardware_preference,
                        hardware_calibration=preferences.hardware_calibration,
                        hardware_decoding=preferences.hardware_decoding,
                        timeout=preferences.timeout, emit=emit, cancel_event=self.cancel,
                        interruption_recovery=preferences.interruption_recovery, private_resume=use_private_resume,
                        checkpoint_id=private_identifier, passphrase=passphrase, retry_id=retry_id,
                        progress=lambda state: self.events.put(("preview_progress" if self.action_only else "progress", state)))
                    if preview_retry:
                        self.events.put(('retry_preview', signature))
                else:
                    prepare_application(preferences, config_path)
                    code = scan_local(inputs, workspace, dependencies=dependencies, recursive=recursive, recovery=None if operation == "scan" else options,
                                      execute=operation != "plan", emit=emit, cancel_event=self.cancel, timeout=preferences.timeout,
                                      sensitive=preferences.sensitive, recovered_dir=preferences.recovered_dir, diagnostics_dir=preferences.diagnostics_dir,
                                      logs_dir=preferences.logs_dir, write_logs=preferences.write_logs, diagnostic_logs=preferences.diagnostic_logs,
                                      cpu_threads=preferences.cpu_threads, max_runners=preferences.max_runners, hardware_decoding=preferences.hardware_decoding,
                                      output_layout=preferences.output_layout, retain_history=preferences.retain_history, retain_mappings=preferences.retain_mappings,
                                      private_resume=use_private_resume, checkpoint_id=private_identifier, passphrase=passphrase)
                if self.action_only:
                    finish({"report": "Summary opened.", "export": "Diagnostic log saved.", "preview_migrate": "Preview ready — no package created.", "plan": "Preview ready — no recovery performed."}[operation])
                else:
                    finish("Finished." if code == 0 else "Finished — review findings and recovery disclosures." if code == 1 else "Incomplete — review blocked or failed work.")
            except KeyboardInterrupt:
                from .migration_resume import SESSION_RETRIES
                can_continue = operation == 'migrate' and reported_id in SESSION_RETRIES and SESSION_RETRIES[reported_id].get('mode') == 'continue'
                finish("Stopped. Continue this migration from Start or Activity while VideoMate stays open; existing outputs will be verified. Export diagnostics before closing."
                    if can_continue else "Stopped. Private checkpoint retained; resume with this Job ID, the original passphrase and the same source, destination and options."
                    if private_retained else "Stopped. Export this session's diagnostics before closing. Restart resume requires a checkpoint enabled before the job.", outcome=False)
            except VideoMateError as error:
                finish(str(error) + " [" + error.code + "]", outcome=False)
                if error.code in {"resume_storage_changed", "resume_output_conflict", "checkpoint_sources_changed"}:
                    self.events.put(("resume_attention", str(error)))
            except OSError:
                finish(str(VideoMateError("io_error")) + " [io_error] Export diagnostic log for the recorded failure stage.", outcome=False)
            except Exception:
                finish(str(VideoMateError("internal_error")), outcome=False)
        self.worker = threading.Thread(target=work, name="videomate-worker", daemon=False)
        self.worker.start()

    def cleanup_selected(self, action):
        if self.busy:
            return
        selected = [int(item) for item in self.files.selection()]
        if not selected or any(self.input_kinds[i] == "Folder" for i in selected):
            self.status.set("Select individual files on Start for manual cleanup; folders are not accepted.")
            self.show("queue")
            return
        inputs = [self.inputs[i] for i in selected]
        phrase = action.upper() + " " + str(len(inputs))
        from tkinter import simpledialog
        warning = "Permanently delete the selected originals. This cannot be undone by VideoMate." if action == "delete" else "Move the selected originals to a hidden .videomate-review folder beside each source, using neutral names. Restore them manually if needed."
        confirmation = simpledialog.askstring("Confirm original-file cleanup", warning + "\nUnreadable does not mean irrecoverable.\nType " + phrase + " to proceed.", parent=self.root)
        if confirmation != phrase:
            return
        self.cancel.clear()
        for widget, _ in self.controls:
            widget.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.begin_progress()
        self.show("jobs")
        def work():
            try:
                from .cleanup import manage_originals
                manage_originals(inputs, action, confirmation, cancel_event=self.cancel,
                                 emit=lambda message: self.events.put(("message", message)))
                self.events.put(("remove_inputs", inputs))
                self.events.put(("done", "Explicit cleanup completed."))
            except KeyboardInterrupt:
                self.events.put(("done", "Cleanup stopped. Earlier completed actions remain in effect; review the activity."))
            except VideoMateError as error:
                self.events.put(("done", str(error)))
            except Exception:
                self.events.put(("done", str(VideoMateError("io_error"))))
        self.worker = threading.Thread(target=work, name="videomate-cleanup", daemon=False)
        self.worker.start()

    def begin_progress(self):
        self.progress_state, self.progress_running = None, True
        self.progress_text.set("Preparing…")
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0, maximum=100)
        if not self.reduce_motion.get():
            self.progress.start(30)

    def update_progress(self, state):
        self.progress_state = state
        if state.total is not None:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=max(1, state.total), value=state.completed)
            self.completed_count.set(str(state.completed))
        stages = {"discovering": "Finding files…", "preparing": "Preparing the migration package…",
                  "processing": "Processing the migration queue…",
                  "waiting_storage": "Source or destination unavailable. Waiting for the same storage to return; Stop is available.",
                  "retrying": "Temporary failure: checking storage and retrying after workers stop…",
                  "inspecting": "Inspecting the current video…", "repairing": "Repairing and verifying the current video…",
                  "copying": "Copying and verifying the current file…", "checking": "Checking the source tree for changes…",
                  "reporting": "Preparing sanitized diagnostics…"}
        if self.cancel.is_set() and self.busy:
            self.status.set("Stopping safely. Waiting for workers to exit; verified outputs remain.")
        elif state.phase in stages:
            self.status.set(stages[state.phase])
        self.progress_text.set(describe(state, running=self.progress_running))

    def poll(self):
        try:
            # Large batches must not monopolize Tk's event loop or the Stop button.
            for _ in range(200):
                kind, text = self.events.get_nowait()
                if kind in {"backend", "backend_error"}:
                    checked_path, message = text
                    selected = Path(self.dependency_path.get()) if self.dependency_path.get() else None
                    if checked_path != selected and self.dependencies != selected:
                        self._tools_recheck_pending = True
                    if not self._tools_recheck_pending and checked_path == selected:
                        self.backend_ready = kind == "backend"
                        self.health.set(message)
                        self.workflow_changed()
                elif kind in {"calibration_ready", "calibration_error"}:
                    if self.worker and self.worker.is_alive():
                        self.events.put((kind, text))
                        break
                    finished = "Optimization stopped." if self.cancel.is_set() or self.closing else "Optimization failed."
                    saved = False
                    if kind == "calibration_ready" and not self.closing and not self.cancel.is_set():
                        codec, record, config_path = text
                        before = self.hardware_calibration
                        self.hardware_calibration = {**before, codec: record}
                        try:
                            save_preferences(config_path, self.preferences())
                            self._saved_settings = self.settings_snapshot()
                            self.settings_state.set("Settings and hardware ranking saved locally.")
                            self.status.set(f"{codec.upper()} hardware ranking saved locally for future jobs.")
                            finished, saved = "Optimization complete.", True
                        except VideoMateError as error:
                            self.hardware_calibration = before
                            self.status.set(str(error))
                            finished = "Optimization not saved. Previous settings were kept."
                    elif self.cancel.is_set() or self.closing:
                        self.status.set("Optimization stopped. Previous settings were kept.")
                    elif not self.closing:
                        self.status.set(text)
                    self.operation_pending = False
                    self.progress_running = False
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=100, value=100 if saved else 0)
                    self.progress_text.set(finished)
                    self.cancel_button.configure(state="disabled")
                    for widget, state in self.controls:
                        widget.configure(state=state)
                    self.refresh_calibration_status()
                    self.privacy_changed()
                    self.workflow_changed()
                    self.refresh_policy()
                elif kind == "resume_attention":
                    from tkinter import messagebox
                    messagebox.showwarning("Resume needs your review", text + "\n\nCheck the selected source/output locally before using Resume migration again.", parent=self.root)
                elif kind == "remove_inputs":
                    for index in range(len(self.inputs) - 1, -1, -1):
                        if self.inputs[index] in text:
                            self.inputs.pop(index)
                            self.input_kinds.pop(index)
                    self.update_queue()
                elif kind == "progress":
                    self.update_progress(text)
                elif kind == "preview_progress":
                    self.status.set("Preview: finding selected inputs…")
                elif kind == 'retry_preview':
                    self.retry_preview = text
                elif kind == 'restore_job_id':
                    self.job.set(text)
                elif kind == 'checkpoint_ready':
                    self.current_migration_checkpoint_ready = True
                elif kind == 'private_retained':
                    self.private_retained_id = text
                    self.workflow_changed()
                elif kind == 'private_checkpoint_removed':
                    if self.private_retained_id == text:
                        self.private_retained_id = None
                    self.workflow_changed()
                elif kind == "message":
                    if text == "Guided preview only. Run recover with --execute to carry out the selected policy.":
                        text = "Preview only. Click Start repair at the bottom of the window to run this policy."
                    self.append(text)
                    if text.startswith("Job: ") and not self.action_only:
                        self.job.set(text[5:])
                    if self.progress_state is None and (match := re.match(r"input-(\d+): [a-z_]+; [a-z_]+$", text)):
                        self.finished_inputs.add(match[1])
                        self.completed_count.set(str(len(self.finished_inputs)))
                    if text.startswith("Inspecting input ") and not self.cancel.is_set():
                        self.status.set(text)
                elif kind == "result_view":
                    self.completed_view = text
                    self.result_text.set('\n'.join(text['text'].splitlines()[:3]) + '\nReview findings for grouped causes, hardware use and loss disclosures.')
                elif kind == "done":
                    if self.worker and self.worker.is_alive():
                        self.events.put((kind, text))
                        break
                    self.operation_pending = False
                    self.active_operation = None
                    if self.action_only:
                        self.status.set(text)
                        self.append(text)
                        for widget, state in self.controls:
                            widget.configure(state=state)
                        self.privacy_changed()
                        self.refresh_policy()
                        self.cancel_button.configure(state="disabled")
                        self.action_only = False
                        continue
                    if self.progress_state:
                        from dataclasses import replace
                        state = self.progress_state
                        self.progress_state = replace(state, elapsed=state.elapsed + max(0, time.monotonic() - state.sampled_at))
                    self.progress_running = False
                    self.status.set(text)
                    self.append(text)
                    for widget, state in self.controls:
                        widget.configure(state=state)
                    self.log_option.configure(state="disabled" if self.sensitive.get() else "normal")
                    self.layout_option.configure(state="disabled" if self.sensitive.get() or self.workflow.get() == "migrate" else "readonly")
                    self.mapping_option.configure(state="disabled" if self.sensitive.get() else "normal")
                    self.workflow_changed()
                    self.refresh_policy()
                    self.cancel_button.configure(state="disabled")
                    self.progress.stop()
                    if self.progress_state and self.progress_state.total is not None:
                        # Tk stop() resets the value on some runtimes. Keep the
                        # actual processed count after completion or cancellation.
                        self.progress.configure(value=self.progress_state.completed)
                    else:
                        self.progress.configure(mode="determinate", maximum=100, value=0)
                    if not self.progress_state:
                        self.progress_text.set("Stopped" if self.cancel.is_set() else "Ready")
        except queue.Empty:
            pass
        if not self.closing and self._tools_recheck_pending and self.setup_worker and not self.setup_worker.is_alive():
            self.check_tools()
        if self.progress_state:
            stopping = self.cancel.is_set() and self.busy
            self.progress_text.set(("Stopping safely · " if stopping else "") + describe(
                self.progress_state, running=self.progress_running and not stopping))
        if self.closing and not self.busy and not (self.setup_worker and self.setup_worker.is_alive()):
            from .migration_resume import clear_session_retries
            from .private_state import LIVE_REPORTS
            clear_session_retries()
            LIVE_REPORTS.clear()
            self.root.destroy()
        else:
            self.poll_timer = self.root.after(100, self.poll)

    def close(self):
        from .migration_resume import SESSION_RETRIES
        session_recovery_available = bool(SESSION_RETRIES)
        running_without_checkpoint = self.busy and self.active_operation == 'migrate' and not self.current_migration_checkpoint_ready
        if session_recovery_available or running_without_checkpoint:
            from tkinter import messagebox
            detail = ('This app session holds a continuation or unresolved retry. Closing discards that session-only state. '
                      'Keep VideoMate open to reuse the existing package.' if session_recovery_available else
                      'This running migration has no private restart checkpoint. Closing stops it and its existing package cannot be resumed after restart.')
            if not messagebox.askyesno('Close VideoMate?',
                    detail + '\n\nPublished outputs remain, but Start new migration needs an empty destination. Close anyway?',
                    parent=self.root, default='no'):
                return
        self.closing = True
        self.cancel.set()
        self.status.set("Stopping workers. Published outputs remain; memory-only diagnostics close with this session.")


def launch(*, config_path=None):
    try:
        import tkinter as tk
        root = create_root()
    except Exception:
        raise VideoMateError("gui_unavailable") from None
    Application(root, config_path=config_path)
    root.mainloop()
    return 0
