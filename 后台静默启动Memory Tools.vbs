' Agents Memory Tools - silent launcher (single port 18922)
' Same architecture as "start.cmd": Python hosts the static workbench and REST API.
' NOTE: keep this file ASCII-only. WSH reads .vbs as ANSI, so non-ASCII text
' can corrupt parsing on Chinese Windows (that is why the old script never ran).
Option Explicit

Dim ws, fso, currentDir, pythonwPath, webAppPath, exec, i, cmd

Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = currentDir

' 1. Kill leftover instance on port 18922 only
ws.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr "":18922 "" ^| findstr ""LISTENING""') do taskkill /F /PID %a", 0, True

' 2. Build the static frontend when index.html is missing
If Not fso.FileExists(currentDir & "\frontend\out\index.html") Then
    ws.Run "cmd /c cd /d " & Chr(34) & currentDir & "\frontend" & Chr(34) & " && npm run build", 0, True
End If

' 3. Start the Python engine silently
pythonwPath = currentDir & "\.venv\Scripts\pythonw.exe"
webAppPath = currentDir & "\web_app.py"
If Not fso.FileExists(pythonwPath) Then pythonwPath = currentDir & "\.venv\Scripts\python.exe"
cmd = Chr(34) & pythonwPath & Chr(34) & " " & Chr(34) & webAppPath & Chr(34)
ws.Run cmd, 0, False

' 4. Open the browser only after the port is really listening
For i = 1 To 80
    Set exec = ws.Exec("cmd /c netstat -ano | findstr "":18922 "" | findstr ""LISTENING""")
    If InStr(exec.StdOut.ReadAll(), "LISTENING") > 0 Then Exit For
    WScript.Sleep 500
Next

ws.Run "cmd /c start " & Chr(34) & Chr(34) & " http://127.0.0.1:18922", 0, True
