Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = currentDir

' 1. Stop any residual processes on ports 18922 and 3000
ws.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr "":18922"" ^| findstr ""LISTENING""') do taskkill /F /PID %a", 0, True
ws.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr "":3000"" ^| findstr ""LISTENING""') do taskkill /F /PID %a", 0, True

' 2. Launch Python core engine silently
pythonwPath = currentDir & "\.venv\Scripts\pythonw.exe"
webAppPath = currentDir & "\web_app.py"
ws.Run chr(34) & pythonwPath & chr(34) & " " & chr(34) & webAppPath & chr(34), 0, False

' 3. Launch Next.js frontend silently
frontendDir = currentDir & "\frontend"
ws.CurrentDirectory = frontendDir
ws.Run "cmd /c pnpm run start", 0, False
ws.CurrentDirectory = currentDir

' 4. Wait 2 seconds and open browser
WScript.Sleep 2000
ws.Run "cmd /c start http://localhost:3000", 0, True