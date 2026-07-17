import os
import unittest
import tempfile
import shutil
from src.steam_config_manager import SteamConfigManager

class TestSteamConfigManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mgr = SteamConfigManager()
        self.mgr.steam_path = self.test_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cs2_discovery_in_libraryfolders_vdf(self):
        """Verify SteamConfigManager parses libraryfolders.vdf cleanly."""
        steamapps_dir = os.path.join(self.test_dir, "steamapps")
        os.makedirs(steamapps_dir, exist_ok=True)
        
        # Create a mock secondary drive path inside test_dir
        mock_drive = os.path.join(self.test_dir, "MockDrive")
        mock_cs2_dir = os.path.join(mock_drive, r"steamapps\common\Counter-Strike Global Offensive\game\bin\win64")
        os.makedirs(mock_cs2_dir, exist_ok=True)
        mock_cs2_exe = os.path.join(mock_cs2_dir, "cs2.exe")
        with open(mock_cs2_exe, "w") as f:
            f.write("mock binary")

        vdf_path = os.path.join(steamapps_dir, "libraryfolders.vdf")
        with open(vdf_path, "w", encoding="utf-8") as f:
            f.write(f'''"libraryfolders"
{{
    "0"
    {{
        "path"		"{self.test_dir.replace(chr(92), chr(92)+chr(92))}"
    }}
    "1"
    {{
        "path"		"{mock_drive.replace(chr(92), chr(92)+chr(92))}"
    }}
}}''')

        discovered = self.mgr.find_cs2_executable()
        self.assertIsNotNone(discovered)
        self.assertEqual(os.path.normpath(discovered), os.path.normpath(mock_cs2_exe))

    def test_clean_cs2_launch_options_vdf_scrubbing(self):
        """Verify clean_cs2_launch_options strips -insecure and -netconport from localconfig.vdf."""
        user_config_dir = os.path.join(self.test_dir, "userdata", "12345678", "config")
        os.makedirs(user_config_dir, exist_ok=True)
        vdf_path = os.path.join(user_config_dir, "localconfig.vdf")

        raw_vdf = '''"UserLocalConfigStore"
{
    "Software"
    {
        "Valve"
        {
            "Steam"
            {
                "Apps"
                {
                    "730"
                    {
                        "LaunchOptions"		"-insecure -console -netconport 2121 -high -novid"
                    }
                    "570"
                    {
                        "LaunchOptions"		"-console"
                    }
                }
            }
        }
    }
}
'''
        with open(vdf_path, "w", encoding="utf-8") as f:
            f.write(raw_vdf)

        cleaned = self.mgr.clean_cs2_launch_options()
        self.assertTrue(cleaned)

        with open(vdf_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('"LaunchOptions"\t\t"-high -novid"', content)
        self.assertNotIn("-insecure", content)
        self.assertNotIn("-netconport", content)
        self.assertIn('"LaunchOptions"\t\t"-console"', content) # App 570 left intact

if __name__ == "__main__":
    unittest.main()
