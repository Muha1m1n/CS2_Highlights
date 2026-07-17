import os
import re
import sys
import glob
import winreg
from typing import Optional, List

class SteamConfigManager:
    """
    Manages Steam local configuration (`localconfig.vdf`) and CS2 binary discovery.
    Ensures that `-insecure`, `-console`, and `-netconport` flags are automatically
    scrubbed from Steam's persistent Launch Options (`LaunchOptions`) so the user
    can safely play competitive matchmaking without VAC errors (`Auto-VAC Shield`).
    """
    def __init__(self):
        self.steam_path = self.find_steam_path()

    def find_steam_path(self) -> str:
        """Locates Steam root directory via Windows Registry or standard paths."""
        if sys.platform == "win32":
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    path, _ = winreg.QueryValueEx(key, "SteamPath")
                    if os.path.exists(path):
                        return os.path.normpath(path)
            except Exception:
                pass

        default_path = r"C:\Program Files (x86)\Steam"
        if os.path.exists(default_path):
            return default_path
        return ""

    def find_cs2_executable(self) -> Optional[str]:
        r"""
        Discovers the absolute path to `cs2.exe` across all Steam library folders.
        Searches `libraryfolders.vdf` and common paths (`C:\`, `D:\`, `E:\`).
        """
        if not self.steam_path:
            return None

        # 1. Check default Steamapps common path
        default_cs2 = os.path.join(
            self.steam_path,
            r"steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe"
        )
        if os.path.exists(default_cs2):
            return default_cs2

        # 2. Parse libraryfolders.vdf for custom drive libraries (D:\, E:\, etc.)
        vdf_path = os.path.join(self.steam_path, r"steamapps\libraryfolders.vdf")
        if os.path.exists(vdf_path):
            try:
                with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                # Extract paths like "path"		"D:\\SteamLibrary"
                library_paths = re.findall(r'"path"\s+"([^"]+)"', content, re.IGNORECASE)
                for lib in library_paths:
                    lib_clean = lib.replace("\\\\", "\\")
                    cand = os.path.join(
                        lib_clean,
                        r"steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe"
                    )
                    if os.path.exists(cand):
                        return cand
            except Exception as e:
                print(f"[SteamConfigManager WARNING] Error reading libraryfolders.vdf: {e}")

        return None

    def clean_cs2_launch_options(self) -> bool:
        """
        Scans all user profiles inside `Steam/userdata/<ID>/config/localconfig.vdf`.
        If AppID `730` (`Counter-Strike 2`) has `"LaunchOptions"` containing `-insecure`
        or `-netconport`, scrubs them out so the user stays 100% VAC-safe.
        Returns True if any vdf files were cleaned.
        """
        if not self.steam_path or not os.path.exists(self.steam_path):
            return False

        cleaned_any = False
        userdata_dir = os.path.join(self.steam_path, "userdata")
        if not os.path.exists(userdata_dir):
            return False

        # Find all localconfig.vdf files across all Steam accounts on this PC
        vdf_files = glob.glob(os.path.join(userdata_dir, "*", "config", "localconfig.vdf"))
        for vdf_path in vdf_files:
            try:
                with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()

                modified = False
                new_lines = []
                in_app_730 = False

                for line in lines:
                    # Check if entering a new quoted section/app block (e.g. "730", "570", "Apps")
                    section_match = re.search(r'^\s*"([^"]+)"\s*$', line)
                    if section_match:
                        sec_name = section_match.group(1)
                        if sec_name == "730":
                            in_app_730 = True
                        elif sec_name.isdigit() or sec_name in ("Apps", "Steam", "Valve", "Software"):
                            in_app_730 = False
                        new_lines.append(line)
                        continue

                    # If inside AppID 730, check for LaunchOptions
                    if in_app_730 and '"LaunchOptions"' in line:
                        match = re.search(r'("LaunchOptions"\s+)"([^"]*)"', line, re.IGNORECASE)
                        if match:
                            prefix = match.group(1)
                            opts = match.group(2)
                            # Remove unsafe flags
                            clean_opts = re.sub(
                                r'\s*-insecure|\s*-console|\s*-netconport\s+\d+',
                                '',
                                opts,
                                flags=re.IGNORECASE
                            ).strip()
                            
                            if clean_opts != opts:
                                print(f"[Auto-VAC Shield] Scrubbing unsafe Launch Options from `{vdf_path}`...")
                                print(f" -> Before: `{opts}`")
                                print(f" -> After:  `{clean_opts}`")
                                modified = True
                                if clean_opts:
                                    # Preserve any other user flags (e.g., -novid -high)
                                    indent = line[:line.find('"LaunchOptions"')]
                                    new_lines.append(f'{indent}"LaunchOptions"\t\t"{clean_opts}"\n')
                                else:
                                    # If clean_opts is empty, keep empty string
                                    indent = line[:line.find('"LaunchOptions"')]
                                    new_lines.append(f'{indent}"LaunchOptions"\t\t""\n')
                                continue

                    new_lines.append(line)

                if modified:
                    # Write back cleaned localconfig.vdf
                    with open(vdf_path, "w", encoding="utf-8") as f:
                        f.writelines(new_lines)
                    cleaned_any = True
                    print(f"[Auto-VAC Shield SUCCESS] Cleaned Launch Options in `{vdf_path}`.")
            except Exception as e:
                print(f"[SteamConfigManager ERROR] Could not clean `{vdf_path}`: {e}")

        return cleaned_any
