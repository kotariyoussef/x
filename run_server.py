import os
import sys
import json
import subprocess
import threading
import webbrowser
import time
import datetime
import tkinter as tk
from tkinter import ttk, messagebox


# ---------- Path / environment helpers ----------
def _get_base_dir():
    """Directory this script (or the frozen executable) lives in."""
    if getattr(sys, "frozen", False) or "nuitka" in sys.modules:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.abspath(__file__))


def _relaunch_in_venv_if_needed():
    """
    If this is running as a plain script (not frozen/compiled) and a virtual
    environment ('venv' or '.venv') exists next to this file, re-exec the
    script using that venv's Python interpreter instead of whatever
    interpreter was originally used to launch it.
    """
    if getattr(sys, "frozen", False) or "nuitka" in sys.modules:
        return  # Frozen builds already bundle their own environment.

    base_dir = _get_base_dir()

    venv_dir = None
    for candidate in ("venv", ".venv"):
        candidate_path = os.path.join(base_dir, candidate)
        if os.path.isdir(candidate_path):
            venv_dir = candidate_path
            break

    if venv_dir is None:
        return  # No venv next to this file — just run with the current interpreter.

    if sys.platform == "win32":
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")

    if not os.path.isfile(venv_python):
        return

    # Already running from the venv interpreter? Nothing to do.
    try:
        if os.path.samefile(sys.executable, venv_python):
            return
    except OSError:
        if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(
            os.path.abspath(venv_python)
        ):
            return

    # Re-launch this exact script (with the same args) using the venv's python.
    result = subprocess.run([venv_python] + sys.argv)
    sys.exit(result.returncode)


_relaunch_in_venv_if_needed()


# License check: validation runs before the GUI starts
try:
    from core.license import validate_or_exit
    validate_or_exit()
except SystemExit as e:
    root = tk.Tk()
    root.withdraw()
    msg = str(e) if str(e) else "This copy of the application is not licensed for this device."
    messagebox.showerror("License Verification", msg)
    sys.exit(1)
except Exception as e:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("License Verification Error", f"Failed to perform license check:\n{e}")
    sys.exit(1)


# ---------- Visual constants ----------
BG = "#0f1115"
PANEL = "#171a21"
PANEL_ALT = "#1d2129"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#3f78e0"
GREEN = "#2ecc71"
RED = "#ff5c5c"
AMBER = "#f5a623"
TEXT_MAIN = "#e8eaed"
TEXT_DIM = "#8a8f98"
FONT = "Segoe UI"


class ServerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("School ERP Server Controller")
        self.root.geometry("480x420")
        self.root.minsize(480, 420)
        self.root.configure(bg=BG)

        self.server_thread = None
        self.server_instance = None
        self.node_process = None
        self.browser_opened = False
        self.is_running = False

        self._build_style()
        self._build_ui()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ---------- UI construction ----------
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
        style.map("Start.TButton",
                  background=[("disabled", "#2a3a30"), ("active", "#27ae60")],
                  foreground=[("disabled", "#5a6b60")])

        style.configure(
            "Stop.TButton",
            background=RED, foreground="#2a0a0a",
            font=(FONT, 11, "bold"), padding=10, borderwidth=0,
        )
        style.map("Stop.TButton",
                  background=[("disabled", "#3a2626"), ("active", "#e64545")],
                  foreground=[("disabled", "#6b5a5a")])

    def _build_ui(self):
        root_frame = tk.Frame(self.root, bg=BG)
        root_frame.pack(fill="both", expand=True, padx=18, pady=18)

        # --- Header ---
        header = tk.Frame(root_frame, bg=BG)
        header.pack(fill="x", pady=(0, 14))

        tk.Label(
            header, text="School ERP", font=(FONT, 16, "bold"),
            bg=BG, fg=TEXT_MAIN,
        ).pack(anchor="w")
        tk.Label(
            header, text="Local Server Controller", font=(FONT, 10),
            bg=BG, fg=TEXT_DIM,
        ).pack(anchor="w")

        # --- Status card ---
        status_card = tk.Frame(root_frame, bg=PANEL, padx=16, pady=14)
        status_card.pack(fill="x", pady=(0, 14))

        status_row = tk.Frame(status_card, bg=PANEL)
        status_row.pack(fill="x")

        self.status_dot = tk.Canvas(status_row, width=14, height=14, bg=PANEL, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 10))
        self._draw_dot(RED)

        status_text_frame = tk.Frame(status_row, bg=PANEL)
        status_text_frame.pack(side="left", fill="x", expand=True)

        self.status_label = tk.Label(
            status_text_frame, text="Stopped", font=(FONT, 13, "bold"),
            bg=PANEL, fg=TEXT_MAIN,
        )
        self.status_label.pack(anchor="w")

        self.status_sub = tk.Label(
            status_text_frame, text="Server is not running", font=(FONT, 9),
            bg=PANEL, fg=TEXT_DIM,
        )
        self.status_sub.pack(anchor="w")

        self.url_label = tk.Label(
            status_card, text="", font=(FONT, 9, "underline"),
            bg=PANEL, fg=ACCENT, cursor="hand2",
        )
        self.url_label.pack(anchor="w", pady=(8, 0))
        self.url_label.bind("<Button-1>", lambda e: webbrowser.open("http://127.0.0.1:8000"))

        # --- Buttons ---
        btn_row = tk.Frame(root_frame, bg=BG)
        btn_row.pack(fill="x", pady=(0, 14))

        self.start_btn = ttk.Button(
            btn_row, text="▶  Start Server", style="Start.TButton",
            command=self.start_services,
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.stop_btn = ttk.Button(
            btn_row, text="■  Stop Server", style="Stop.TButton",
            command=self.stop_services, state=tk.DISABLED,
        )
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

        # --- Log panel ---
        log_label = tk.Label(
            root_frame, text="ACTIVITY LOG", font=(FONT, 8, "bold"),
            bg=BG, fg=TEXT_DIM,
        )
        log_label.pack(anchor="w")

        log_frame = tk.Frame(root_frame, bg=PANEL_ALT)
        log_frame.pack(fill="both", expand=True, pady=(4, 0))

        self.log_text = tk.Text(
            log_frame, bg=PANEL_ALT, fg=TEXT_MAIN, insertbackground=TEXT_MAIN,
            font=("Consolas", 9), relief="flat", padx=10, pady=8,
            state="disabled", wrap="word",
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        self._log("Ready. Click \"Start Server\" to begin.")

    def _draw_dot(self, color):
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 12, 12, fill=color, outline="")

    def _log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    # ---------- State helpers ----------
    def _set_status(self, state):
        """state: 'starting' | 'running' | 'stopping' | 'stopped' | 'error'"""
        if state == "starting":
            self._draw_dot(AMBER)
            self.status_label.config(text="Starting…")
            self.status_sub.config(text="Launching background services")
            self.url_label.config(text="")
        elif state == "running":
            self._draw_dot(GREEN)
            self.status_label.config(text="Running")
            self.status_sub.config(text="Server is live")
            self.url_label.config(text="🔗 http://127.0.0.1:8000  (click to open)")
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

    # ---------- WhatsApp service helpers ----------
    def prepare_and_launch_whatsapp(self, service_dir):
        """
        Check npm for a newer whatsapp-web.js release than the one pinned in
        whatsapp_service/package.json. If a newer version exists, install it
        automatically. Either way, launch the Node WhatsApp automation
        service afterwards. Runs in a background thread so it never blocks
        the Django/Waitress startup.
        """
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

        try:
            current_version = None
            pkg_json_path = os.path.join(service_dir, "package.json")
            if os.path.isfile(pkg_json_path):
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    pkg_data = json.load(f)
                deps = pkg_data.get("dependencies", {})
                current_version = deps.get("whatsapp-web.js")

            result = subprocess.run(
                [npm_cmd, "view", "whatsapp-web.js", "version"],
                cwd=service_dir,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=creationflags,
            )

            if result.returncode != 0 or not result.stdout.strip():
                self.root.after(0, lambda: self._log(
                    "Could not check whatsapp-web.js updates (offline or npm error)."))
            else:
                latest_version = result.stdout.strip()
                cleaned_current = (current_version or "").lstrip("^~=v ").strip()

                if cleaned_current and cleaned_current != latest_version:
                    self.root.after(0, lambda: self._log(
                        f"whatsapp-web.js update available: {cleaned_current} → {latest_version}. Installing…"))

                    install_result = subprocess.run(
                        [npm_cmd, "install", f"whatsapp-web.js@{latest_version}"],
                        cwd=service_dir,
                        capture_output=True,
                        text=True,
                        timeout=180,
                        creationflags=creationflags,
                    )

                    if install_result.returncode == 0:
                        self.root.after(0, lambda: self._log(
                            f"whatsapp-web.js updated to v{latest_version}."))
                    else:
                        err_tail = (install_result.stderr or install_result.stdout or "").strip()[-300:]
                        self.root.after(0, lambda: self._log(
                            f"whatsapp-web.js update failed, continuing with existing version. ({err_tail})"))
                elif cleaned_current:
                    self.root.after(0, lambda: self._log(
                        f"whatsapp-web.js is up to date (v{latest_version})."))
                else:
                    self.root.after(0, lambda: self._log(
                        f"Latest whatsapp-web.js version on npm: {latest_version}"))

        except subprocess.TimeoutExpired:
            self.root.after(0, lambda: self._log("whatsapp-web.js update check/install timed out."))
        except FileNotFoundError:
            self.root.after(0, lambda: self._log("npm not found — skipped whatsapp-web.js update check."))
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self._log(f"whatsapp-web.js update check failed: {error_msg}"))

        # Launch the Node service regardless of whether the update check/install succeeded,
        # so a failed update never prevents the WhatsApp service from starting.
        try:
            self.node_process = subprocess.Popen(
                ["node", "server.js"],
                cwd=service_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self.root.after(0, lambda: self._log("WhatsApp automation service launched."))
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self._log(f"WhatsApp service failed to launch: {error_msg}"))
            self.root.after(0, lambda: messagebox.showwarning(
                "Warning", f"Failed to launch WhatsApp automation service:\n{error_msg}"))

    # ---------- Core logic (same behavior, now with logging/feedback) ----------
    def start_services(self):
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._set_status("starting")
        self._log("Starting server…")

        base_dir = _get_base_dir()
        service_dir = os.path.join(base_dir, 'whatsapp_service')

        self._log("Checking for whatsapp-web.js updates…")
        threading.Thread(
            target=self.prepare_and_launch_whatsapp, args=(service_dir,), daemon=True
        ).start()

        self.server_thread = threading.Thread(target=self.run_waitress, daemon=True)
        self.server_thread.start()

        threading.Thread(target=self.open_browser_delayed, daemon=True).start()

    def run_waitress(self):
        try:
            self.root.after(0, lambda: self._log("Loading Django & Waitress handlers..."))
            from waitress.server import create_server
            from django.contrib.staticfiles.handlers import StaticFilesHandler
            from school_erp.wsgi import application
            
            wsgi_app = StaticFilesHandler(application)
            self.server_instance = create_server(wsgi_app, host="127.0.0.1", port=8000)
            self.is_running = True
            self.root.after(0, lambda: self._set_status("running"))
            self.root.after(0, lambda: self._log("Waitress server bound to 127.0.0.1:8000."))
            self.server_instance.run()
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self._log(f"Server error: {error_msg}"))
            self.root.after(0, lambda: self._set_status("error"))
            self.root.after(0, lambda: messagebox.showerror("Server Error", f"Waitress server encountered an error:\n{error_msg}"))
        finally:
            self.is_running = False
            self.root.after(0, self.update_ui_stopped)

    def open_browser_delayed(self):
        time.sleep(1.5)
        if self.server_instance:
            url = "http://127.0.0.1:8000"
            opened_fullscreen = False

            # Try launching popular browsers in fullscreen mode via subprocess on Windows
            if sys.platform == 'win32':
                import shutil
                # Paths or execution commands for common browsers
                browsers = [
                    {"cmd": "chrome", "flag": "--start-fullscreen"},
                    {"cmd": "msedge", "flag": "--start-fullscreen"},
                ]
                
                for browser in browsers:
                    if shutil.which(browser["cmd"]): # Check if browser exists in PATH
                        try:
                            subprocess.Popen([browser["cmd"], browser["flag"], url])
                            opened_fullscreen = True
                            self.root.after(0, lambda b=browser["cmd"]: self._log(f"Opened {b.upper()} in fullscreen."))
                            break
                        except Exception:
                            continue

            # Fallback if not Windows or if Chrome/Edge couldn't be launched directly
            if not opened_fullscreen:
                webbrowser.open(url)
                self.root.after(0, lambda: self._log(f"Opened default browser at {url}"))
                
            self.browser_opened = True

    def update_ui_stopped(self):
        self._set_status("stopped")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def stop_services(self):
        self.stop_btn.config(state=tk.DISABLED)
        self._set_status("stopping")
        self._log("Stopping server…")

        if self.node_process:
            try:
                self.node_process.terminate()
                self.node_process.wait(timeout=2)
                self._log("WhatsApp service stopped.")
            except subprocess.TimeoutExpired:
                self.node_process.kill()
                self._log("WhatsApp service force-killed (timeout).")
            except Exception as e:
                self._log(f"Error stopping WhatsApp service: {e}")
            self.node_process = None

        if self.server_instance:
            try:
                self.server_instance.close()
                self._log("Waitress server closed.")
            except Exception as e:
                self._log(f"Error closing server: {e}")
            self.server_instance = None

        if self.browser_opened and sys.platform == 'win32':
            try:
                subprocess.Popen("taskkill /im msedge.exe /f", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.Popen("taskkill /im chrome.exe /f", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._log("Closed browser windows.")
            except Exception as e:
                self._log(f"Could not close browser: {e}")
            self.browser_opened = False

        self.update_ui_stopped()

    def on_closing(self):
        if self.is_running:
            if not messagebox.askokcancel("Quit", "The server is still running. Stop it and quit?"):
                return
            self.stop_services()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ServerApp(root)
    root.mainloop()