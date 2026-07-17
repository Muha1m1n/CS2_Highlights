Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = ScriptDir

VenvPython = FSO.BuildPath(ScriptDir, ".venv\Scripts\pythonw.exe")
If Not FSO.FileExists(VenvPython) Then
    VenvPython = FSO.BuildPath(ScriptDir, ".venv\Scripts\python.exe")
End If

If FSO.FileExists(VenvPython) Then
    WshShell.Run """" & VenvPython & """ -m src.desktop_app", 0, False
Else
    WshShell.Run "pythonw -m src.desktop_app", 0, False
End If
