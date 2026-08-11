import datetime
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from urllib.request import urlopen


# ---------------------------------------------------------------------------
# Version parsing (stdlib only)
# ---------------------------------------------------------------------------

def _parse_npm_version(raw):
    """
    Parse an npm dependency version specifier into a (major, minor, patch) tuple.

    Handles common forms: 1.2.3  ^1.2.3  ~1.2.3  >=1.2.3  v1.2.3
    Returns None if the string cannot be parsed.
    Never raises.
    """
    if not raw:
        return None
    try:
        # Strip all leading non-digit characters (^, ~, >=, v, spaces, …)
        cleaned = re.sub(r'^[^\d]*', '', str(raw).strip())
        # Drop pre-release / build metadata after the first space or hyphen
        cleaned = re.split(r'[\s\-]', cleaned)[0]
        parts = cleaned.split('.')
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Network / port helpers
# ---------------------------------------------------------------------------

def is_port_available(port, host="0.0.0.0"):
    """Return True if *port* is available for binding on *host*."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
            return True
    except OSError:
        return False


def find_free_port(start_port, host="0.0.0.0", max_port=65535):
    """
    Return the first available TCP port >= start_port on *host*.

    Note: this is a TOCTOU check — a port may be grabbed by another process
    between the check and binding. Callers should handle EADDRINUSE on bind.
    """
    port = start_port
    while port <= max_port:
        if is_port_available(port, host):
            return port
        port += 1
    raise RuntimeError(f"No available TCP port found starting from {start_port}.")


def get_local_ip():
    """Return the local LAN IP address without requiring internet access."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# Process management (pure — no Tkinter)
# ---------------------------------------------------------------------------

def _stop_process_tree(process, name, log_fn=None):
    """
    Terminate *process* and its entire process group / tree.

    Pure process management: contains zero Tkinter calls.

    Args:
        process:  subprocess.Popen instance (or None — no-op).
        name:     Human-readable label used in log messages.
        log_fn:   Optional callable(str).  Receives status messages.
                  If None, messages are silently discarded.
                  The caller decides whether to route via root.after or direct.

    Blocks until the process exits or timeouts expire.
    """
    _log = log_fn if callable(log_fn) else (lambda _msg: None)

    if process is None:
        return

    if process.poll() is not None:
        _log(f"{name} was already stopped.")
        return

    try:
        _log(f"Stopping {name}...")

        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _log(f"{name} did not exit after taskkill.")

        else:
            import signal

            pgid = None
            try:
                pgid = os.getpgid(process.pid)
            except OSError:
                _log(f"{name}: process group not found; terminating process directly.")

            if pgid is not None:
                try:
                    os.killpg(pgid, signal.SIGTERM)
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _log(f"{name} did not stop gracefully. Force-killing process group...")
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                        process.wait(timeout=5)
                    except Exception:
                        pass
                except ProcessLookupError:
                    pass  # Process group already gone
            else:
                try:
                    process.terminate()
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _log(f"{name} did not stop gracefully. Force-killing process...")
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except Exception:
                        pass

        _log(f"{name} stopped.")

    except ProcessLookupError:
        _log(f"{name} was already stopped.")
    except Exception as exc:
        _log(f"Error stopping {name}: {exc}")


def _run_subprocess(args, **kwargs):
    """
    subprocess.run() wrapper that injects CREATE_NO_WINDOW on Windows only.
    Never passes creationflags on Linux / macOS.
    """
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(args, **kwargs)


# ---------------------------------------------------------------------------
# Path / environment helpers
# ---------------------------------------------------------------------------

def _get_base_dir():
    """Directory containing this script, or the frozen / Nuitka executable."""
    if getattr(sys, "frozen", False) or "nuitka" in sys.modules:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.abspath(__file__))


def _get_config_path():
    return os.path.join(_get_base_dir(), "run_server_config.json")


def _load_local_config():
    try:
        with open(_get_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_local_config(config):
    try:
        with open(_get_config_path(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except OSError:
        pass


def _relaunch_in_venv_if_needed():
    """
    If running as a plain script and a venv exists next to this file,
    re-exec the script using the venv's Python interpreter.
    No-op when frozen / Nuitka.
    """
    if getattr(sys, "frozen", False) or "nuitka" in sys.modules:
        return

    base_dir = _get_base_dir()
    venv_dir = None
    for candidate in ("venv", ".venv"):
        path = os.path.join(base_dir, candidate)
        if os.path.isdir(path):
            venv_dir = path
            break

    if venv_dir is None:
        return

    if sys.platform == "win32":
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")

    if not os.path.isfile(venv_python):
        return

    try:
        if os.path.samefile(sys.executable, venv_python):
            return
    except OSError:
        if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(
            os.path.abspath(venv_python)
        ):
            return

    sys.exit(subprocess.run([venv_python] + sys.argv).returncode)


_relaunch_in_venv_if_needed()


# ---------------------------------------------------------------------------
# License check — runs before the GUI starts
# ---------------------------------------------------------------------------

try:
    from core.license import validate_or_exit
    validate_or_exit()
except SystemExit as _e:
    _root = tk.Tk()
    _root.withdraw()
    _msg = str(_e) if str(_e) else "This copy of the application is not licensed for this device."
    messagebox.showerror("License Verification", _msg)
    sys.exit(1)
except Exception as _e:
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "License Verification Error",
        f"Failed to perform license check:\n{_e}",
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------

BG       = "#0f1115"
PANEL    = "#171a21"
PANEL_ALT = "#1d2129"
ACCENT   = "#4f8cff"
GREEN    = "#2ecc71"
RED      = "#ff5c5c"
AMBER    = "#f5a623"
TEXT_MAIN = "#e8eaed"
TEXT_DIM  = "#8a8f98"
FONT     = "Segoe UI"


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class ServerApp:
    """
    Tkinter GUI that manages the Django/Waitress server and the WhatsApp
    automation Node.js service as independent background threads.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("School ERP Server Controller")
        self.root.geometry("480x420")
        self.root.minsize(480, 420)
        self.root.configure(bg=BG)

        # ── Shared state ───────────────────────────────────────────────────────
        self.server_thread   = None        # django background thread
        self.server_instance = None        # waitress server object
        self.node_process    = None        # WhatsApp node subprocess
        self.browser_opened  = False
        self.is_running      = False
        self.local_ip        = get_local_ip()
        self._stopping       = False

        self._startup_lock   = threading.Lock()
        self._startup_id     = 0           # incremented on every Start / Stop

        self.django_port     = None
        self.whatsapp_port   = None
        self.server_ready    = threading.Event()

        # ── Security ──────────────────────────────────────────────────────────
        self.whatsapp_api_key = self._load_or_create_api_key()

        # ── GUI ───────────────────────────────────────────────────────────────
        self._build_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # =========================================================================
    # API key
    # =========================================================================

    def _load_or_create_api_key(self):
        """
        Load the persisted API key from run_server_config.json, or generate a
        new one if the file is missing, malformed, or the key looks invalid.
        The key is NEVER logged.
        """
        config = _load_local_config()
        api_key = config.get("WA_API_KEY")
        if not isinstance(api_key, str) or len(api_key) < 10:
            api_key = secrets.token_urlsafe(32)
            config["WA_API_KEY"] = api_key
            _save_local_config(config)
        return api_key

    # =========================================================================
    # Startup session management
    # =========================================================================

    def _new_startup_id(self):
        """Increment and return the startup counter under a lock."""
        with self._startup_lock:
            self._startup_id += 1
            return self._startup_id

    def _current_startup_id(self):
        with self._startup_lock:
            return self._startup_id

    def _is_valid_session(self, startup_id):
        """
        Return True iff this startup_id is still the active session and no
        shutdown is in progress.  Background threads call this before every
        state-mutating operation.
        """
        return not self._stopping and startup_id == self._current_startup_id()

    # =========================================================================
    # Tkinter-safe logging
    # =========================================================================

    def _log(self, message):
        """Append a timestamped entry to the activity log.  Main thread only."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _thread_log(self, message):
        """
        Thread-safe log helper.  Safe to call from any thread.
        Schedules _log on the Tkinter main thread via root.after.
        """
        # Capture message in default arg to avoid late-binding closure issues.
        self.root.after(0, lambda m=message: self._log(m))

    def _make_bg_log(self):
        """
        Return a log_fn suitable for passing to _stop_process_tree from a
        background thread.  Each call schedules exactly one root.after.
        """
        return lambda msg: self.root.after(0, lambda m=msg: self._log(m))

    # =========================================================================
    # UI construction
    # =========================================================================

    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Card.TFrame", background=PANEL)
        style.configure("Root.TFrame", background=BG)

        style.configure(
            "Start.TButton",
            background=GREEN, foreground="#0b1f12",
            font=(FONT, 11, "bold"), padding=10, borderwidth=0,
        )
        style.map(
            "Start.TButton",
            background=[("disabled", "#2a3a30"), ("active", "#27ae60")],
            foreground=[("disabled", "#5a6b60")],
        )
        style.configure(
            "Stop.TButton",
            background=RED, foreground="#2a0a0a",
            font=(FONT, 11, "bold"), padding=10, borderwidth=0,
        )
        style.map(
            "Stop.TButton",
            background=[("disabled", "#3a2626"), ("active", "#e64545")],
            foreground=[("disabled", "#6b5a5a")],
        )

    def _build_ui(self):
        root_frame = tk.Frame(self.root, bg=BG)
        root_frame.pack(fill="both", expand=True, padx=18, pady=18)

        # Header
        header = tk.Frame(root_frame, bg=BG)
        header.pack(fill="x", pady=(0, 14))
        tk.Label(header, text="School ERP", font=(FONT, 16, "bold"),
                 bg=BG, fg=TEXT_MAIN).pack(anchor="w")
        tk.Label(header, text="Local Server Controller", font=(FONT, 10),
                 bg=BG, fg=TEXT_DIM).pack(anchor="w")

        # Status card
        status_card = tk.Frame(root_frame, bg=PANEL, padx=16, pady=14)
        status_card.pack(fill="x", pady=(0, 14))

        status_row = tk.Frame(status_card, bg=PANEL)
        status_row.pack(fill="x")

        self.status_dot = tk.Canvas(status_row, width=14, height=14,
                                    bg=PANEL, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 10))
        self._draw_dot(RED)

        status_text_frame = tk.Frame(status_row, bg=PANEL)
        status_text_frame.pack(side="left", fill="x", expand=True)

        self.status_label = tk.Label(status_text_frame, text="Stopped",
                                     font=(FONT, 13, "bold"), bg=PANEL, fg=TEXT_MAIN)
        self.status_label.pack(anchor="w")

        self.status_sub = tk.Label(status_text_frame, text="Server is not running",
                                   font=(FONT, 9), bg=PANEL, fg=TEXT_DIM)
        self.status_sub.pack(anchor="w")

        self.url_label = tk.Label(status_card, text="",
                                  font=(FONT, 9, "underline"), bg=PANEL,
                                  fg=ACCENT, cursor="hand2")
        self.url_label.pack(anchor="w", pady=(8, 0))
        self.url_label.bind("<Button-1>", self._open_url)

        # Buttons
        btn_row = tk.Frame(root_frame, bg=BG)
        btn_row.pack(fill="x", pady=(0, 14))

        self.start_btn = ttk.Button(btn_row, text="▶  Start Server",
                                    style="Start.TButton",
                                    command=self.start_services)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.stop_btn = ttk.Button(btn_row, text="■  Stop Server",
                                   style="Stop.TButton",
                                   command=self.stop_services,
                                   state=tk.DISABLED)
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

        # Activity log
        tk.Label(root_frame, text="ACTIVITY LOG", font=(FONT, 8, "bold"),
                 bg=BG, fg=TEXT_DIM).pack(anchor="w")

        log_frame = tk.Frame(root_frame, bg=PANEL_ALT)
        log_frame.pack(fill="both", expand=True, pady=(4, 0))

        self.log_text = tk.Text(
            log_frame, bg=PANEL_ALT, fg=TEXT_MAIN,
            insertbackground=TEXT_MAIN, font=("Consolas", 9),
            relief="flat", padx=10, pady=8,
            state="disabled", wrap="word",
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        self._log('Ready. Click "Start Server" to begin.')

    def _open_url(self, event=None):
        if self.django_port:
            webbrowser.open(f"http://127.0.0.1:{self.django_port}")

    def _draw_dot(self, color):
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 12, 12, fill=color, outline="")

    def _set_status(self, state):
        """Update the status card.  Must only be called on the main thread."""
        if state == "starting":
            self._draw_dot(AMBER)
            self.status_label.config(text="Starting…")
            self.status_sub.config(text="Launching background services")
            self.url_label.config(text="")
        elif state == "running":
            self._draw_dot(GREEN)
            self.status_label.config(text="Running")
            self.status_sub.config(text="Server is live")
            if self.django_port:
                self.url_label.config(
                    text=(
                        f"LOCAL: http://127.0.0.1:{self.django_port}\n"
                        f"LAN:   http://{self.local_ip}:{self.django_port}"
                    )
                )
            else:
                self.url_label.config(text="")
        elif state == "stopping":
            self._draw_dot(AMBER)
            self.status_label.config(text="Stopping…")
            self.status_sub.config(text="Shutting down services")
            self.url_label.config(text="")
        elif state == "stopped":
            self._draw_dot(RED)
            self.status_label.config(text="Stopped")
            self.status_sub.config(text="Server is not running")
            self.url_label.config(text="")
        elif state == "error":
            self._draw_dot(RED)
            self.status_label.config(text="Error")
            self.status_sub.config(text="Server failed to start — see log")
            self.url_label.config(text="")

    # =========================================================================
    # npm auto-update
    # =========================================================================

    def _check_npm_update(self, npm_cmd, package_json_path, service_dir, startup_id):
        """
        Check whether a newer stable version of whatsapp-web.js exists on npm
        and install it automatically if so.

        Called from a background thread.  Entirely non-fatal: any failure is
        logged and startup continues with the already-installed version.
        Uses _thread_log throughout (never touches Tkinter directly).
        """
        self._thread_log("Checking for whatsapp-web.js updates...")

        # -- Read current version from package.json ---------------------------
        current_version_raw = None
        try:
            with open(package_json_path, "r", encoding="utf-8") as f:
                pkg_data = json.load(f)
            current_version_raw = pkg_data.get("dependencies", {}).get("whatsapp-web.js")
        except Exception as exc:
            self._thread_log(
                f"Could not read package.json: {exc}. Skipping update check."
            )
            return

        # -- Query npm registry -----------------------------------------------
        try:
            result = _run_subprocess(
                [npm_cmd, "view", "whatsapp-web.js", "version"],
                cwd=service_dir,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            self._thread_log(
                "whatsapp-web.js update check timed out. "
                "Continuing with installed version."
            )
            return
        except FileNotFoundError:
            self._thread_log("npm not found during update check. Skipping.")
            return
        except Exception as exc:
            self._thread_log(f"whatsapp-web.js update check error: {exc}")
            return

        if result.returncode != 0 or not result.stdout.strip():
            self._thread_log(
                "Could not check whatsapp-web.js updates (offline or npm error). "
                "Continuing with installed version."
            )
            return

        latest_raw = result.stdout.strip()
        current_tuple = _parse_npm_version(current_version_raw)
        latest_tuple  = _parse_npm_version(latest_raw)

        if current_tuple is None:
            self._thread_log(
                f"Latest whatsapp-web.js on npm: {latest_raw} "
                f"(installed specifier not parseable: {current_version_raw!r})."
            )
            return

        if latest_tuple is None:
            self._thread_log(
                f"Could not parse npm version {latest_raw!r}. Skipping update."
            )
            return

        current_str = ".".join(str(x) for x in current_tuple)
        latest_str  = ".".join(str(x) for x in latest_tuple)

        if latest_tuple > current_tuple:
            # Clearly newer — proceed with install
            self._thread_log(
                f"whatsapp-web.js update available: {current_str} → {latest_str}. Installing…"
            )

            if not self._is_valid_session(startup_id):
                return   # Session stopped during registry query

            try:
                install_result = _run_subprocess(
                    [npm_cmd, "install", f"whatsapp-web.js@{latest_raw}"],
                    cwd=service_dir,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if install_result.returncode == 0:
                    self._thread_log(f"whatsapp-web.js updated to v{latest_raw}.")
                else:
                    err_tail = (
                        install_result.stderr or install_result.stdout or ""
                    ).strip()[-300:]
                    self._thread_log(
                        f"whatsapp-web.js update failed, continuing with existing version. "
                        f"({err_tail})"
                    )
            except subprocess.TimeoutExpired:
                self._thread_log(
                    "whatsapp-web.js update installation timed out. "
                    "Continuing with existing version."
                )
            except Exception as exc:
                self._thread_log(f"whatsapp-web.js update error: {exc}")

        elif latest_tuple < current_tuple:
            # npm reports an older version — do NOT downgrade
            self._thread_log(
                f"whatsapp-web.js: local ({current_str}) is ahead of npm ({latest_str}). "
                "Skipping update."
            )
        else:
            self._thread_log(f"whatsapp-web.js is up to date (v{latest_str}).")

    # =========================================================================
    # WhatsApp health check
    # =========================================================================

    def _whatsapp_health_check(self, port, timeout=25):
        """
        Poll GET http://127.0.0.1:<port>/status until the Express server responds.

        Returns:
            (reachable: bool, wa_status: str | None)

        SEMANTICS — these are independent:
          reachable=True  →  the Node.js HTTP server is listening.
          wa_status       →  the WhatsApp *client* state as reported by server.js
                             (INITIALIZING, QR_RECEIVED, AUTHENTICATED, READY, …).

        HTTP 200 + INITIALIZING does NOT mean WhatsApp is connected.
        /status is public in server.js — no API key is sent.
        """
        url = f"http://127.0.0.1:{port}/status"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        try:
                            data = json.loads(resp.read(4096))
                            return True, data.get("status")
                        except Exception:
                            return True, None
            except Exception:
                pass
            time.sleep(0.5)
        return False, None

    # =========================================================================
    # WhatsApp background thread
    # =========================================================================

    def prepare_and_launch_whatsapp(self, service_dir, startup_id):
        """
        Background thread entry point.

        Responsibilities:
          1. Validate Node.js and npm availability (independently).
          2. Validate required service files.
          3. Run npm auto-update check (non-fatal).
          4. Launch node server.js with correct environment and process flags.
          5. Detect early failures (EADDRINUSE → retry, other errors → log & return).
          6. Run health check and report Node HTTP + WhatsApp client state separately.

        Fully independent of the Django startup thread.
        """
        if not self._is_valid_session(startup_id):
            return

        node_cmd = "node.exe" if sys.platform == "win32" else "node"
        npm_cmd  = "npm.cmd"  if sys.platform == "win32" else "npm"

        # -- 1. Check Node.js -------------------------------------------------
        node_available = False
        try:
            r = _run_subprocess([node_cmd, "--version"],
                                capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                node_available = True
                self._thread_log(f"Node.js found: {r.stdout.strip()}")
            else:
                self._thread_log("ERROR: Node.js version check returned non-zero.")
        except FileNotFoundError:
            self._thread_log("ERROR: Node.js is not installed or not in PATH.")
        except subprocess.TimeoutExpired:
            self._thread_log("ERROR: Node.js version check timed out.")

        # -- 2. Check npm (independent) ---------------------------------------
        npm_available = False
        try:
            r = _run_subprocess([npm_cmd, "--version"],
                                capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                npm_available = True
                self._thread_log(f"npm found: {r.stdout.strip()}")
            else:
                self._thread_log("npm check returned non-zero. Skipping update check.")
        except FileNotFoundError:
            self._thread_log("npm not found. Skipping update check.")
        except subprocess.TimeoutExpired:
            self._thread_log("npm version check timed out. Skipping update check.")

        # -- 3. Validate required files ---------------------------------------
        server_js_path   = os.path.join(service_dir, "server.js")
        package_json_path = os.path.join(service_dir, "package.json")

        if not node_available:
            self._thread_log("WhatsApp service cannot start without Node.js.")
            return

        if not os.path.isdir(service_dir):
            self._thread_log(
                f"ERROR: WhatsApp service directory not found: {service_dir}"
            )
            return

        if not os.path.isfile(server_js_path):
            self._thread_log("ERROR: whatsapp_service/server.js not found.")
            return

        if not os.path.isfile(package_json_path):
            self._thread_log("ERROR: whatsapp_service/package.json not found.")
            return

        # -- 4. npm auto-update (non-fatal) -----------------------------------
        if npm_available and self._is_valid_session(startup_id):
            self._check_npm_update(npm_cmd, package_json_path, service_dir, startup_id)

        if not self._is_valid_session(startup_id):
            return  # Session stopped during npm update

        # -- 5. Retrieve the port assigned by start_services() ----------------
        wa_port = self.whatsapp_port
        if wa_port is None:
            self._thread_log(
                "ERROR: WhatsApp port was not assigned. Cannot start service."
            )
            return

        self._thread_log(
            f"Starting WhatsApp automation service on port {wa_port}..."
        )

        # -- 6. Build Popen kwargs (platform-correct, no creationflags on Linux)
        popen_kwargs = {
            "cwd":    service_dir,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True

        env = os.environ.copy()
        env["WA_PORT"]    = str(wa_port)
        env["WA_API_KEY"] = self.whatsapp_api_key  # never logged

        # -- 7. Launch Node, retry on EADDRINUSE (up to 3 attempts) -----------
        launched_process = None
        for _attempt in range(1, 4):
            if not self._is_valid_session(startup_id):
                return

            try:
                process = subprocess.Popen(
                    [node_cmd, "server.js"],
                    env=env,
                    **popen_kwargs,
                )
            except FileNotFoundError:
                self._thread_log("ERROR: node executable not found during Popen.")
                return
            except Exception as exc:
                self._thread_log(
                    f"ERROR: Failed to launch WhatsApp service: {exc}"
                )
                return

            # Brief wait to catch fast failures (EADDRINUSE, MODULE_NOT_FOUND …)
            time.sleep(1.5)

            exit_code = process.poll()
            if exit_code is None:
                # Process is alive — guard before storing
                if not self._is_valid_session(startup_id):
                    # Session was invalidated while we waited. Kill the orphan
                    # silently (no GUI log needed for a dead session).
                    _stop_process_tree(
                        process,
                        "WhatsApp service (stale session)",
                        log_fn=None,
                    )
                    return
                launched_process = process
                break  # Success

            # Process exited — collect diagnostics
            try:
                outs, errs = process.communicate(timeout=3)
            except Exception:
                outs, errs = b"", b""

            raw_diag  = (errs or outs or b"").decode("utf-8", errors="replace")[:500]
            # Strip API key from diagnostics before any logging
            safe_diag = raw_diag.replace(self.whatsapp_api_key, "[REDACTED]")

            if (
                "EADDRINUSE" in raw_diag
                or "address already in use" in raw_diag.lower()
            ):
                if not self._is_valid_session(startup_id):
                    return
                try:
                    wa_port = find_free_port(wa_port + 1, host="127.0.0.1")
                    self.whatsapp_port = wa_port
                    env["WA_PORT"] = str(wa_port)
                    os.environ["WA_PORT"] = str(wa_port)
                    try:
                        from django.conf import settings
                        if settings.configured:
                            settings.WHATSAPP_SERVICE_PORT = str(wa_port)
                    except Exception:
                        pass
                    self._thread_log(
                        f"WhatsApp port conflict. Retrying on port {wa_port}..."
                    )
                    continue
                except RuntimeError as exc2:
                    self._thread_log(
                        f"ERROR: No available port for WhatsApp service: {exc2}"
                    )
                    return

            # Non-port failure
            self._thread_log(
                f"ERROR: WhatsApp service exited during startup. {safe_diag}"
            )
            self.root.after(0, lambda: messagebox.showwarning(
                "WhatsApp Service",
                "WhatsApp automation service failed to start.\n"
                "See the activity log for details.",
            ))
            return

        else:
            self._thread_log(
                "ERROR: WhatsApp service failed to start after multiple port attempts."
            )
            return

        # Store the process only if launch succeeded
        self.node_process = launched_process

        # -- 8. Health check: verify Express is listening ---------------------
        self._thread_log("Waiting for WhatsApp service to respond...")
        reachable, wa_status = self._whatsapp_health_check(wa_port, timeout=25)

        if not self._is_valid_session(startup_id):
            return

        if reachable:
            # Report Node HTTP availability and WhatsApp client state separately
            self._thread_log(
                f"WhatsApp automation service is listening on port {wa_port}."
            )
            if wa_status == "READY":
                self._thread_log("WhatsApp client is connected and ready.")
            elif wa_status in ("QR_RECEIVED", "INITIALIZING", "AUTHENTICATED"):
                self._thread_log(
                    f"WhatsApp client status: {wa_status}. "
                    "Open the dashboard to scan the QR code if prompted."
                )
            elif wa_status in ("DISCONNECTED", "ERROR", "AUTHENTICATION_FAILED"):
                self._thread_log(
                    f"WhatsApp client status: {wa_status}. "
                    "The dashboard will show more details."
                )
            elif wa_status:
                self._thread_log(f"WhatsApp client status: {wa_status}.")
            else:
                self._thread_log("WhatsApp client status: unknown.")
        else:
            self._thread_log(
                "WhatsApp service started but health check timed out "
                "(Chromium/Puppeteer may still be initializing)."
            )

    # =========================================================================
    # Django / Waitress background thread
    # =========================================================================

    def run_waitress(self, startup_id):
        """
        Background thread: import Django + Waitress, bind, serve until stopped.
        Fully independent of the WhatsApp startup thread.
        All UI mutations go through root.after.
        """
        self._thread_log("Loading Django & Waitress handlers...")

        try:
            from django.contrib.staticfiles.handlers import StaticFilesHandler
            from school_erp.wsgi import application
            from waitress.server import create_server
        except Exception as exc:
            self._thread_log(f"ERROR: Failed to load Django/Waitress: {exc}")
            self.root.after(0, lambda: self._set_status("error"))
            self.root.after(0, lambda: messagebox.showerror(
                "Django Error", f"Failed to load Django/Waitress:\n{exc}"
            ))
            node_snap = self.node_process
            self.root.after(
                0, lambda: self._handle_django_failure(startup_id, node_snap)
            )
            return

        if not self._is_valid_session(startup_id):
            return

        # -- Bind Waitress, retry on port conflict ----------------------------
        server = None
        for _attempt in range(1, 6):
            if not self._is_valid_session(startup_id):
                return
            try:
                server = create_server(
                    StaticFilesHandler(application),
                    host="0.0.0.0",
                    port=self.django_port,
                )
                break
            except OSError as exc:
                msg = str(exc).lower()
                if (
                    "address already in use" in msg
                    or "port is already allocated" in msg
                ):
                    self._thread_log(
                        f"Django port {self.django_port} was taken. Retrying..."
                    )
                    try:
                        new_port = find_free_port(self.django_port + 1)
                        self.django_port = new_port
                        self._thread_log(
                            f"Waitress port re-selected: {self.django_port}"
                        )
                        continue
                    except RuntimeError as port_exc:
                        self._thread_log(
                            f"ERROR: Could not find available Django port. {port_exc}"
                        )
                        self.root.after(0, lambda: self._set_status("error"))
                        node_snap = self.node_process
                        self.root.after(
                            0,
                            lambda: self._handle_django_failure(startup_id, node_snap),
                        )
                        return
                # Non-port OSError
                self._thread_log(f"ERROR: Waitress failed to bind: {exc}")
                self.root.after(0, lambda: self._set_status("error"))
                self.root.after(0, lambda e=exc: messagebox.showerror(
                    "Server Error", f"Waitress failed to bind:\n{e}"
                ))
                node_snap = self.node_process
                self.root.after(
                    0,
                    lambda: self._handle_django_failure(startup_id, node_snap),
                )
                return
        else:
            self._thread_log(
                "ERROR: Django failed to start after multiple port attempts."
            )
            self.root.after(0, lambda: self._set_status("error"))
            node_snap = self.node_process
            self.root.after(
                0,
                lambda: self._handle_django_failure(startup_id, node_snap),
            )
            return

        # -- Guard before marking the session live ----------------------------
        if not self._is_valid_session(startup_id):
            try:
                server.close()
            except Exception:
                pass
            return

        self.server_instance = server

        # Narrow race window: if stop arrived between the guard and the
        # assignment above, close the server immediately.
        if not self._is_valid_session(startup_id):
            try:
                server.close()
            except Exception:
                pass
            self.server_instance = None
            return

        self.is_running = True
        self.server_ready.set()

        self.root.after(0, lambda: self._set_status("running"))
        self.root.after(0, lambda: self._log(
            f"Django server is listening on {self.local_ip}:{self.django_port} "
            "(LAN accessible)."
        ))

        # -- Block until Waitress is closed by stop_services() ----------------
        try:
            server.run()
        except Exception as exc:
            self._thread_log(f"Waitress server error: {exc}")
        finally:
            self.is_running = False
            # Unexpected exit (not triggered by stop_services) — only clean up
            # if this is still the active session.
            if not self._stopping and startup_id == self._current_startup_id():
                node_snap = self.node_process
                if node_snap is not None:
                    self.node_process    = None
                    self.whatsapp_port   = None
                self.root.after(
                    0,
                    lambda: self._handle_unexpected_django_exit(
                        startup_id, node_snap
                    ),
                )

    # =========================================================================
    # Django failure / unexpected-exit handlers  (main thread)
    # =========================================================================

    def _handle_django_failure(self, startup_id, node_proc_snapshot):
        """
        Called on the main thread when Django startup fails.

        Guards on startup_id so a stale thread never resets a newer session.
        Stops the WhatsApp process that belongs to *this* session only
        (verified by object identity, not just non-None).
        Cleanup runs in a daemon thread to avoid freezing the GUI.
        """
        if startup_id != self._current_startup_id():
            return   # A newer session is already running — leave it alone.

        # Prevent another Start while we are cleaning up.
        self._stopping = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self._set_status("error")

        # Capture and clear the node_process ref that belongs to this session.
        to_stop = None
        if (
            node_proc_snapshot is not None
            and node_proc_snapshot is self.node_process
        ):
            to_stop              = node_proc_snapshot
            self.node_process    = None
            self.whatsapp_port   = None

        self.is_running    = False
        self.django_port   = None
        self.server_ready.clear()

        def _cleanup():
            bg_log = self._make_bg_log()
            if to_stop is not None:
                _stop_process_tree(to_stop, "WhatsApp service", log_fn=bg_log)

            def _reenable():
                self._stopping = False
                self.start_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.DISABLED)

            self.root.after(0, _reenable)

        threading.Thread(
            target=_cleanup, daemon=True, name="django-fail-cleanup"
        ).start()

    def _handle_unexpected_django_exit(self, startup_id, node_proc_snapshot):
        """
        Called on the main thread when Django exits unexpectedly after having
        started successfully.  Same session-ownership rules apply.
        """
        if startup_id != self._current_startup_id():
            return

        self._stopping = True

        to_stop = None
        if (
            node_proc_snapshot is not None
            and node_proc_snapshot is self.node_process
        ):
            to_stop            = node_proc_snapshot
            self.node_process  = None
            self.whatsapp_port = None

        def _cleanup():
            bg_log = self._make_bg_log()
            if to_stop is not None:
                _stop_process_tree(to_stop, "WhatsApp service", log_fn=bg_log)
            self.root.after(0, self.update_ui_stopped)

        threading.Thread(
            target=_cleanup, daemon=True, name="django-exit-cleanup"
        ).start()

    # =========================================================================
    # Browser opener  (background thread)
    # =========================================================================

    def open_browser_delayed(self, startup_id):
        """
        Wait until Django is accepting connections on its port, then open the
        system browser to the local URL.
        """
        if not self.server_ready.wait(timeout=30):
            if self._is_valid_session(startup_id):
                self._thread_log("Timed out waiting for Django to become ready.")
            return

        if not self._is_valid_session(startup_id):
            return

        # TCP readiness poll — confirms the port is truly accepting connections.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not self._is_valid_session(startup_id):
                return
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex(("127.0.0.1", self.django_port)) == 0:
                        break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            if self._is_valid_session(startup_id):
                self._thread_log("Timed out waiting for Django port to open.")
            return

        if not self._is_valid_session(startup_id):
            return

        url = f"http://127.0.0.1:{self.django_port}"
        try:
            webbrowser.open(url)
            self._thread_log(f"Opened browser at {url}")
            self.browser_opened = True
        except Exception as exc:
            self._thread_log(f"Could not open browser: {exc}")

    # =========================================================================
    # Start services
    # =========================================================================

    def start_services(self):
        """
        Main-thread entry point.  Select ports, then launch WhatsApp and Django
        as fully independent background threads.
        """
        if self.is_running or self._stopping:
            return

        startup_id = self._new_startup_id()
        self.server_ready.clear()
        self.browser_opened = False
        self._stopping      = False

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._set_status("starting")
        self._log("Starting server…")

        # -- Port selection (main thread, before any threads start) -----------
        try:
            self.django_port    = find_free_port(8000)
            self._log(f"Waitress port selected: {self.django_port}")
            # WhatsApp port bound to localhost only
            self.whatsapp_port  = find_free_port(3000, host="127.0.0.1")
            self._log(f"WhatsApp service port selected: {self.whatsapp_port}")
            os.environ["WA_PORT"] = str(self.whatsapp_port)
            os.environ["WA_API_KEY"] = self.whatsapp_api_key
        except Exception as exc:
            self._log(f"ERROR: Could not find available ports: {exc}")
            self._set_status("error")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            return

        base_dir    = _get_base_dir()
        service_dir = os.path.join(base_dir, "whatsapp_service")

        # -- WhatsApp thread (independent — does NOT block Django) ------------
        threading.Thread(
            target=self.prepare_and_launch_whatsapp,
            args=(service_dir, startup_id),
            daemon=True,
            name=f"wa-{startup_id}",
        ).start()

        # -- Django thread (independent — does NOT wait for WhatsApp) ---------
        self.server_thread = threading.Thread(
            target=self.run_waitress,
            args=(startup_id,),
            daemon=True,
            name=f"django-{startup_id}",
        )
        self.server_thread.start()

        # -- Browser opener thread --------------------------------------------
        threading.Thread(
            target=self.open_browser_delayed,
            args=(startup_id,),
            daemon=True,
            name=f"browser-{startup_id}",
        ).start()

    # =========================================================================
    # Stop services
    # =========================================================================

    def _do_stop_background(self, node_proc, server_inst, then=None):
        """
        Background thread: stop the captured process and server, then call
        *then* on the main thread.

        Accepts explicit objects (not self.node_process / self.server_instance)
        so a stale stop thread can never kill a newer session's processes.
        """
        bg_log = self._make_bg_log()

        if node_proc is not None:
            _stop_process_tree(node_proc, "WhatsApp service", log_fn=bg_log)

        if server_inst is not None:
            try:
                server_inst.close()
                bg_log("Waitress server closed.")
            except Exception as exc:
                bg_log(f"Error closing Waitress: {exc}")

        # Unblock any thread waiting on server_ready (e.g. browser opener).
        self.server_ready.set()

        if then is not None:
            self.root.after(0, then)

    def stop_services(self):
        """
        Initiate a clean shutdown.

        Immediately captures and clears process / server refs so no other code
        can touch the same objects.  Actual blocking teardown happens in a
        background thread to keep the GUI responsive.
        """
        if self._stopping:
            return
        self._stopping = True
        self._new_startup_id()   # Invalidate all active startup threads

        self.stop_btn.config(state=tk.DISABLED)
        self._set_status("stopping")
        self._log("Stopping server…")

        # Capture and immediately clear so no future code can inherit them.
        node_proc            = self.node_process
        self.node_process    = None
        srv                  = self.server_instance
        self.server_instance = None
        self.django_port     = None
        self.whatsapp_port   = None

        threading.Thread(
            target=self._do_stop_background,
            args=(node_proc, srv, self.update_ui_stopped),
            daemon=True,
            name="stop-services",
        ).start()

    def update_ui_stopped(self):
        """Reset the GUI to the Stopped state.  Must be called on the main thread."""
        self._set_status("stopped")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.is_running    = False
        self._stopping     = False
        self.django_port   = None
        self.whatsapp_port = None
        self.server_ready.clear()

    # =========================================================================
    # Window close
    # =========================================================================

    def on_closing(self):
        """
        Handle the window's X button.

        If services are running, prompt the user.  Cleanup runs in a background
        thread; root.destroy() is called only after cleanup completes — never
        after a fixed timer.
        """
        server_running = self.server_instance is not None
        node_running   = (
            self.node_process is not None
            and self.node_process.poll() is None
        )

        if server_running or node_running:
            if not messagebox.askokcancel(
                "Quit",
                "School ERP services are still running. Stop them and quit?",
            ):
                return

        # Capture refs and mark stopping — only if not already doing so.
        node_proc = None
        srv       = None
        if not self._stopping:
            self._stopping       = True
            self._new_startup_id()
            node_proc            = self.node_process
            self.node_process    = None
            srv                  = self.server_instance
            self.server_instance = None
            self.django_port     = None
            self.whatsapp_port   = None

        def _cleanup_then_destroy():
            bg_log = self._make_bg_log()
            if node_proc is not None:
                _stop_process_tree(node_proc, "WhatsApp service", log_fn=bg_log)
            if srv is not None:
                try:
                    srv.close()
                except Exception:
                    pass
            self.server_ready.set()
            # Destroy the window only after cleanup has actually finished.
            self.root.after(0, self.root.destroy)

        threading.Thread(
            target=_cleanup_then_destroy,
            daemon=True,
            name="on-closing",
        ).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = ServerApp(root)
    root.mainloop()
