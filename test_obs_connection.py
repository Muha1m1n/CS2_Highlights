"""
Test script to verify Python communication with OBS Studio via WebSocket v5.

Prerequisites:
1. OBS Studio must be open and running.
2. In OBS Studio, go to Tools -> WebSocket Server Settings -> check "Enable WebSocket Server".
3. Default port is 4455. If you set a password, update the `OBS_PASSWORD` variable below.
"""

import sys
import time
import psutil

try:
    from obswebsocket import obsws, requests
except ImportError:
    print("[ERROR] `obswebsocket` is not installed. Please run `pip install obs-websocket-py psutil`.")
    sys.exit(1)

# --- CONFIGURATION ---
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = ""  # Leave empty if no password is set in OBS WebSocket settings


def is_obs_running() -> bool:
    """Check if obs64.exe or obs.exe is currently running."""
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and 'obs' in proc.info['name'].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False


def main():
    print("=== OBS Studio WebSocket Connection Test ===")
    
    # 1. Check if OBS process is running
    print("\n[Step 1] Checking if OBS Studio process is running...")
    if not is_obs_running():
        print("[WARNING] OBS Studio process (`obs64.exe`) not detected in background.")
        print("-> Please open OBS Studio on your computer before continuing.")
    else:
        print("[SUCCESS] OBS Studio is running!")

    # 2. Attempt WebSocket connection
    print(f"\n[Step 2] Attempting to connect to OBS WebSocket at {OBS_HOST}:{OBS_PORT}...")
    try:
        cl = obsws(OBS_HOST, OBS_PORT, OBS_PASSWORD, timeout=3)
        cl.connect()
        
        # Get OBS version info
        version_info = cl.call(requests.GetVersion())
        print("[SUCCESS] Connected to OBS Studio!")
        print(f" -> OBS Version: {version_info.getObsVersion()}")
        print(f" -> WebSocket Version: {version_info.getObsWebSocketVersion()}")

        # 3. Check recording status
        print("\n[Step 3] Checking OBS recording status...")
        record_status = cl.call(requests.GetRecordStatus())
        print(f" -> Is Currently Recording: {record_status.getOutputActive()}")
        
        # Get recording output folder
        try:
            record_dir = cl.call(requests.GetRecordDirectory())
            print(f" -> Output Directory: {record_dir.getRecordDirectory()}")
        except Exception as e:
            print(f" -> Could not retrieve output directory: {e}")

        cl.disconnect()
        print("\n[ALL CHECKS PASSED] Python is fully authorized to control OBS Studio automatically!")
        
    except Exception as e:
        print(f"\n[ERROR] Could not connect to OBS WebSocket: {e}")
        print("\nTroubleshooting Steps:")
        print("1. Ensure OBS Studio is currently open on your desktop.")
        print("2. In OBS, go to: Tools -> WebSocket Server Settings.")
        print("3. Ensure 'Enable WebSocket Server' is CHECKED.")
        print("4. Check if Server Port is 4455.")
        print("5. If 'Enable Authentication' is checked in OBS, copy the password and enter it into `OBS_PASSWORD` inside `test_obs_connection.py` (or uncheck authentication for local testing).")


if __name__ == "__main__":
    main()
