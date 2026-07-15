"""
OBS Studio Controller (`src/obs_controller.py`)

Provides programmatic control over OBS Studio via WebSocket v5 (`obs-websocket-py`).
Allows Python to start and stop recordings precisely when CS2 demo playback reaches
highlight intervals, and automatically locates the newly recorded `.mp4` file for renaming.
"""

import os
import sys
import time
import glob
from typing import Optional, Dict, Any

try:
    from obswebsocket import obsws, requests, exceptions
except ImportError:
    obsws = None  # Will be caught on initialization if library is missing


class OBSController:
    """
    Controller for OBS Studio via WebSocket v5 (`localhost:4455`).
    
    Prerequisites:
    1. OBS Studio must be open.
    2. Go to Tools -> WebSocket Server Settings -> Check "Enable WebSocket Server".
    """

    def __init__(self, host: str = "localhost", port: int = 4455, password: str = "", timeout: int = 3):
        if obsws is None:
            raise ImportError("`obswebsocket` library not found. Please run `pip install obs-websocket-py`.")
        
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.client: Optional[obsws] = None
        self.connected = False

    def connect(self, max_retries: int = 3, retry_delay: float = 2.0) -> bool:
        """
        Establishes a WebSocket connection to OBS Studio.
        """
        if self.connected and self.client:
            return True

        for attempt in range(1, max_retries + 1):
            try:
                self.client = obsws(self.host, self.port, self.password, timeout=self.timeout)
                self.client.connect()
                
                # Check version info to confirm successful handshake
                version = self.client.call(requests.GetVersion())
                self.connected = True
                print(f"[OBSController SUCCESS] Connected to OBS Studio v{version.getObsVersion()} (WebSocket v{version.getObsWebSocketVersion()})")
                return True
            except Exception as e:
                if attempt < max_retries:
                    print(f"[OBSController] Attempt {attempt}/{max_retries} to connect failed ({e}). Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"[OBSController ERROR] Could not connect to OBS Studio at {self.host}:{self.port} after {max_retries} attempts.")
                    print(" -> Ensure OBS Studio is open and Tools -> WebSocket Server Settings is enabled.")
                    self.client = None
                    self.connected = False
                    return False
        return False

    def disconnect(self):
        """Cleanly closes the WebSocket connection to OBS Studio."""
        if self.client and self.connected:
            try:
                self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.connected = False
        print("[OBSController] Disconnected from OBS Studio.")

    def get_record_status(self) -> Dict[str, Any]:
        """
        Returns current OBS recording status:
        `{"is_recording": bool, "is_paused": bool, "timecode": str}`
        """
        if not self.connected or not self.client:
            if not self.connect(max_retries=1):
                raise ConnectionError("OBSController not connected.")
        
        try:
            status = self.client.call(requests.GetRecordStatus())
            return {
                "is_recording": status.getOutputActive(),
                "is_paused": status.getOutputPaused(),
                "timecode": status.getOutputTimecode()
            }
        except Exception as e:
            print(f"[OBSController ERROR] Failed to fetch record status: {e}")
            raise

    def get_record_directory(self) -> str:
        """Retrieves the directory folder where OBS Studio saves recorded videos."""
        if not self.connected or not self.client:
            if not self.connect(max_retries=1):
                raise ConnectionError("OBSController not connected.")
        
        try:
            res = self.client.call(requests.GetRecordDirectory())
            return res.getRecordDirectory()
        except Exception as e:
            print(f"[OBSController ERROR] Failed to fetch record directory: {e}")
            raise

    def start_recording(self) -> bool:
        """
        Commands OBS Studio to start recording immediately (`requests.StartRecord()`).
        If already recording, does nothing and returns True.
        """
        status = self.get_record_status()
        if status["is_recording"]:
            print("[OBSController] OBS is already recording.")
            return True

        print("[OBSController] Sending `StartRecord` command to OBS...")
        try:
            self.client.call(requests.StartRecord())
            
            # Brief pause to verify recording started
            time.sleep(0.5)
            new_status = self.get_record_status()
            if new_status["is_recording"]:
                print("[OBSController SUCCESS] Recording started successfully!")
                return True
            else:
                print("[OBSController ERROR] `StartRecord` command sent, but output_active remains False.")
                return False
        except Exception as e:
            print(f"[OBSController ERROR] Failed to start recording: {e}")
            return False

    def stop_recording(self, wait_for_file_flush: bool = True, timeout: float = 10.0) -> Optional[str]:
        """
        Commands OBS Studio to stop recording (`requests.StopRecord()`).
        
        If `wait_for_file_flush` is True, polls OBS until output turns inactive and checks
        the recording folder for the newest video file produced, returning its absolute path.
        """
        status = self.get_record_status()
        if not status["is_recording"]:
            print("[OBSController] OBS is not currently recording.")
            return None

        print("[OBSController] Sending `StopRecord` command to OBS...")
        try:
            self.client.call(requests.StopRecord())
            
            if not wait_for_file_flush:
                return None

            print("[OBSController] Waiting for OBS to finalize and flush video buffer to disk...")
            start_time = time.time()
            while time.time() - start_time < timeout:
                curr_status = self.get_record_status()
                if not curr_status["is_recording"]:
                    print("[OBSController SUCCESS] Recording finalized!")
                    # Give Windows / filesystem an extra second to release file lock
                    time.sleep(1.0)
                    latest_clip = self.find_latest_recording()
                    if latest_clip:
                        print(f"[OBSController] Located new recording: {latest_clip}")
                    return latest_clip
                time.sleep(0.5)
            
            print("[OBSController WARNING] Timeout exceeded while waiting for recording to finalize.")
            return self.find_latest_recording()
            
        except Exception as e:
            print(f"[OBSController ERROR] Failed to stop recording: {e}")
            return None

    def find_latest_recording(self, extensions=('mp4', 'mkv', 'mov')) -> Optional[str]:
        """
        Scans the OBS recording output folder and returns the absolute path of the
        most recently modified video file.
        """
        try:
            rec_dir = self.get_record_directory()
            if not rec_dir or not os.path.exists(rec_dir):
                return None

            files = []
            for ext in extensions:
                pattern = os.path.join(rec_dir, f"*.{ext}")
                files.extend(glob.glob(pattern))

            if not files:
                return None

            # Find newest file by modification timestamp
            latest_file = max(files, key=os.path.getmtime)
            return os.path.abspath(latest_file)
        except Exception as e:
            print(f"[OBSController ERROR] Error finding latest recording: {e}")
            return None


if __name__ == "__main__":
    print("=== OBS Studio Controller Standalone Test ===")
    try:
        obs_ctrl = OBSController()
        if obs_ctrl.connect(max_retries=1):
            print("\n[SUCCESS] Connected to OBS WebSocket!")
            status = obs_ctrl.get_record_status()
            print(f" -> Is Currently Recording: {status['is_recording']}")
            rec_dir = obs_ctrl.get_record_directory()
            print(f" -> Recording Folder: {rec_dir}")
            obs_ctrl.disconnect()
        else:
            print("\n[INFO] Could not connect to OBS Studio.")
            print("To test live commands, open OBS Studio on your desktop and re-run this test.")
    except Exception as err:
        print(f"\n[ERROR] Test failed: {err}")
