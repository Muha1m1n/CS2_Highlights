Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\snoop\OneDrive\Documents\ClipperCS2"
WshShell.Run """C:\Users\snoop\AppData\Local\Python\pythoncore-3.14-64\python.exe"" ""C:\Users\snoop\OneDrive\Documents\ClipperCS2\src\desktop_app.py""", 0, False
