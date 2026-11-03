Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = currentDir

' 清理旧进程
ws.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr "":18922"" ^| findstr ""LISTENING""') do taskkill /F /PID %a", 0, True

pythonwPath = currentDir & "\.venv\Scripts\pythonw.exe"
webAppPath = currentDir & "\web_app.py"
ws.Run chr(34) & pythonwPath & chr(34) & " " & chr(34) & webAppPath & chr(34), 0, False
