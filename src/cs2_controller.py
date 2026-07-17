"""
CS2 NetCon Controller (`src/cs2_controller.py`)

Provides programmatic control over Counter-Strike 2 via its local network console (`-netconport 2121`).
Allows Python to load demo files, jump to specific ticks, control playback speed, and apply
cinematic HUD settings (`cl_draw_only_deathnotices 1`, `spec_show_xray 0`) cleanly before recording.
"""

import os
import sys
import time
import socket
import psutil
import subprocess
from typing import Optional


class CS2NetCon:
    """
    Controller for Counter-Strike 2 via TCP network console (`-netconport`).
    
    To use this, CS2 must be launched with the launch options:
        -netconport 2121
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 2121, timeout: float = 3.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.connected = False

    def is_cs2_running(self) -> bool:
        """Checks whether `cs2.exe` process is currently running."""
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] and proc.info['name'].lower() == 'cs2.exe':
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return False

    def launch_cs2_if_needed(self, wait_seconds: int = 15) -> bool:
        """
        Checks if CS2 is open. If not, attempts to launch CS2 via Steam protocol URI
        with `-netconport <port>` appended.
        """
        if self.is_cs2_running():
            print("[CS2NetCon] CS2 process (`cs2.exe`) is already running.")
            return True

        print(f"[CS2NetCon] Launching CS2 with `-insecure -console -netconport {self.port}`...")
        try:
            try:
                from src.steam_config_manager import SteamConfigManager
                steam_mgr = SteamConfigManager()
                # Scour library folders for direct cs2.exe binary
                cs2_binary = steam_mgr.find_cs2_executable()
                if cs2_binary and os.path.exists(cs2_binary):
                    print(f"[Auto-VAC Shield] Direct cs2.exe discovered: `{cs2_binary}`")
                    print("[Auto-VAC Shield] Launching direct binary (Bypasses persistent Steam Launch Options)...")
                    subprocess.Popen([
                        cs2_binary,
                        "-insecure",
                        "-console",
                        "-netconport", str(self.port),
                        "-steam"
                    ])
                else:
                    print("[Auto-VAC Shield] Direct cs2.exe not found, falling back to Steam AppLaunch...")
                    steam_exe = r"C:\Program Files (x86)\Steam\steam.exe"
                    if sys.platform == "win32" and os.path.exists(steam_exe):
                        subprocess.Popen([steam_exe, "-applaunch", "730", "-insecure", "-console", "-netconport", str(self.port)])
                    else:
                        launch_url = f"steam://run/730//-insecure -console -netconport {self.port}"
                        if sys.platform == "win32":
                            os.startfile(launch_url)
                        else:
                            subprocess.Popen(["xdg-open", launch_url])
            except Exception as inner_e:
                print(f"[Auto-VAC Shield WARNING] Fallback launch triggered ({inner_e})...")
                launch_url = f"steam://run/730//-insecure -console -netconport {self.port}"
                if sys.platform == "win32":
                    os.startfile(launch_url)
                else:
                    subprocess.Popen(["xdg-open", launch_url])
            
            print(f"[CS2NetCon] Waiting up to {wait_seconds}s for CS2 window to boot...")
            start_time = time.time()
            while time.time() - start_time < wait_seconds:
                if self.is_cs2_running():
                    print("[CS2NetCon] CS2 process detected!")
                    # Give the game engine an extra moment to open TCP port
                    time.sleep(4.0)
                    return True
                time.sleep(1.0)
            
            print("[CS2NetCon WARNING] CS2 process did not appear within timeout.")
            return False
        except Exception as e:
            print(f"[CS2NetCon ERROR] Failed to launch CS2: {e}")
            return False

    def connect(self, max_retries: int = 5, retry_delay: float = 2.0) -> bool:
        """
        Establishes a TCP socket connection to CS2 NetCon server.
        """
        if self.connected and self.sock:
            return True

        for attempt in range(1, max_retries + 1):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(self.timeout)
                self.sock.connect((self.host, self.port))
                self.connected = True
                print(f"[CS2NetCon SUCCESS] Connected to CS2 NetCon on {self.host}:{self.port}")
                return True
            except (ConnectionRefusedError, socket.timeout, OSError) as e:
                if attempt < max_retries:
                    print(f"[CS2NetCon] Attempt {attempt}/{max_retries} to connect failed ({e}). Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"[CS2NetCon ERROR] Could not connect to CS2 NetCon on {self.host}:{self.port} after {max_retries} attempts.")
                    print(" -> Ensure CS2 is running and was launched with: `-netconport 2121`")
                    self.sock = None
                    self.connected = False
                    return False
        return False

    def disconnect(self):
        """Closes the socket connection to CS2 NetCon cleanly and scrubs VAC launch options."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.connected = False
        print("[CS2NetCon] Disconnected from CS2 NetCon.")
        try:
            from src.steam_config_manager import SteamConfigManager
            SteamConfigManager().clean_cs2_launch_options()
        except Exception as e:
            print(f"[Auto-VAC Shield WARNING] Could not run Steam config check on disconnect: {e}")

    def send_command(self, command: str, read_response: bool = False) -> str:
        """
        Sends a raw console command string to CS2 over TCP.
        Appends newline `\n` automatically.
        """
        if not self.connected or not self.sock:
            if not self.connect(max_retries=1):
                raise ConnectionError("Cannot send command: CS2 NetCon is not connected.")

        try:
            full_cmd = command.strip() + "\n"
            self.sock.sendall(full_cmd.encode("utf-8"))
            
            output = ""
            if read_response:
                try:
                    # Non-blocking or short read to grab echo/response
                    self.sock.settimeout(0.3)
                    while True:
                        data = self.sock.recv(4096)
                        if not data:
                            break
                        output += data.decode("utf-8", errors="ignore")
                except socket.timeout:
                    pass
                finally:
                    self.sock.settimeout(self.timeout)
            return output.strip()
        except (ConnectionAbortedError, ConnectionResetError, OSError) as sock_err:
            print(f"[CS2NetCon] Socket disconnected while sending `{command}` ({sock_err}). Cleanly updating connection status.")
            self.connected = False
            self.sock = None
            return ""
        except Exception as e:
            print(f"[CS2NetCon ERROR] Failed to send command `{command}`: {e}")
            self.connected = False
            self.sock = None
            return ""

    # =========================================================================
    # DEMO PLAYBACK & NAVIGATION COMMANDS
    # =========================================================================

    def play_demo(self, demo_path: str):
        """
        Loads and starts playing a `.dem` file inside CS2.
        """
        # Ensure forward slashes for Source 2 console command
        clean_path = os.path.abspath(demo_path).replace("\\", "/")
        print(f"[CS2NetCon] Loading demo: {clean_path}")
        self.send_command(f'playdemo "{clean_path}"')

    def goto_tick(self, tick: int, relative: bool = False):
        """
        Teleports demo playback to a specific tick number.
        If `relative=True`, jumps `tick` ticks relative to current position.
        """
        cmd = f"demo_goto {tick} 1" if relative else f"demo_goto {tick}"
        self.send_command(cmd)

    def pause_demo(self):
        """Pauses demo playback (`demo_pause`)."""
        self.send_command("demo_pause")

    def resume_demo(self):
        """Resumes demo playback (`demo_resume`)."""
        self.send_command("demo_resume")

    def set_timescale(self, scale: float = 1.0):
        """
        Sets demo playback speed (`demo_timescale <speed>`).
        - 1.0 = Normal real-time speed (for recording)
        - 0.5 = Half-speed slow motion
        - 10.0+ = Fast-forward between highlights
        """
        self.send_command(f"demo_timescale {scale}")

    # =========================================================================
    # CINEMATIC UI & HUD SETTINGS
    # =========================================================================

    def setup_cinematic_hud(self, player_name: Optional[str] = None):
        """
        Applies clean, esports-grade HUD configurations:
        - Hides radar, inventory, health/ammo bars; leaves ONLY kill feed in top-right (`cl_draw_only_deathnotices 1`).
        - Disables X-Ray wallhacks (`spec_show_xray 0`) for an authentic live-match feel.
        - Hides the bottom demo scrubber control bar (`r_show_demo_ui 0`).
        - Optionally locks camera to `player_name` in First-Person view (`spec_mode 1`).
        """
        print("[CS2NetCon] Applying spectator HUD settings (Player Profile visible, No X-Ray, Hidden Demo UI)...")
        commands = [
            "sv_cheats 1",                   # Required for some offline demo UI tweaks
            "cl_draw_only_deathnotices 0",   # 0 = Keeps player profile, ammo, health, weapon & avatars VISIBLE
            "cl_drawhud 1",                  # Ensure HUD panels are enabled
            "spec_show_xray 0",              # Disables X-Ray player outlines through walls for authentic feel
            "demo_timescale 1.0",            # Ensure normal speed
        ]
        
        if player_name:
            commands.append("spec_mode 1")                         # Lock to 1st-person camera
            commands.append(f'spec_player "{player_name}"')        # Lock view to target player by exact name string
            commands.append(f"spec_player {player_name}")          # Fallback without quotes
        
        for cmd in commands:
            self.send_command(cmd)
        self.suppress_demo_ui()

    def suppress_demo_ui(self):
        """
        Forces the bottom replay timeline scrubber bar (`Demo UI`) and spectator
        keybinding hints to close/hide across all Source 2 UI modes without toggling open.
        """
        commands = [
            "demoui_close",                  # Panorama explicit close command
            "demoui false",                  # User requested exact command
            "demoui 0",                      # Boolean zero format
            "demo_ui_mode 0",                # Source 2 timeline mode
            "r_show_demo_ui 0",              # Legacy render command
            "cl_spec_show_bindings 0",       # Hide "[G]: Enable Mouse..." hint bar
        ]
        for cmd in commands:
            self.send_command(cmd)

    def lock_camera_to_player(self, player_name: str):
        """
        Locks spectator camera directly into `player_name`'s First-Person (In-Eye / POV) view.
        Sends Source 2 `spec_player` across 6 pulses while ticking to ensure exact POV lock.
        Also invokes `suppress_demo_ui()` on every pulse so any tick jump or camera switch
        cannot pop open the bottom demo playback scrubber bar (`Demo UI`).
        """
        if not player_name:
            return
        print(f"[CS2NetCon] Locking camera to 1st-person POV for player: {player_name} (and suppressing Demo UI playbar)...")
        for _ in range(6):
            self.send_command("spec_mode 1")                         # First person POV
            self.send_command(f'spec_player "{player_name}"')        # Lock view with quotes
            self.send_command(f"spec_player {player_name}")          # Lock view without quotes
            self.suppress_demo_ui()
            self.send_command("spec_mode 1")                         # Re-assert first person after slot/name selection
            time.sleep(0.3)

    def restore_normal_hud(self):
        """Restores standard HUD, X-Ray, and Demo control menus."""
        if not self.connected or not self.sock:
            print("[CS2NetCon] Socket already closed or disconnected. Skipping HUD restoration.")
            return
        print("[CS2NetCon] Restoring normal spectator HUD settings...")
        commands = [
            "cl_draw_only_deathnotices 0",
            "spec_show_xray 1",
            "r_show_demo_ui 1",
            "demo_ui_mode 2",
            "cl_spec_show_bindings 1",
        ]
        for cmd in commands:
            try:
                self.send_command(cmd)
            except Exception as e:
                print(f"[CS2NetCon WARNING] Could not send HUD restore command `{cmd}` ({e}). Stopping HUD restoration.")
                break


if __name__ == "__main__":
    # Quick standalone connectivity test
    print("=== CS2 NetCon Controller Standalone Test ===")
    netcon = CS2NetCon()
    if netcon.is_cs2_running():
        print("[SUCCESS] CS2 is running! Testing connection...")
        if netcon.connect(max_retries=2):
            print("[SUCCESS] NetCon connected! Testing echo...")
            netcon.send_command("echo [ClipperCS2] Connected to Python NetCon Controller successfully!")
            netcon.disconnect()
    else:
        print("[INFO] CS2 (`cs2.exe`) is not currently open on this machine.")
        print("To test live commands, launch CS2 with `-netconport 2121` and run `python src/cs2_controller.py`.")
