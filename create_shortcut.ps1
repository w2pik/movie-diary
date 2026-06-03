$ws = New-Object -ComObject WScript.Shell
$dt = [Environment]::GetFolderPath('Desktop')
$sc = $ws.CreateShortcut("$dt\MovieDiary.lnk")
$sc.TargetPath = 'D:\01_Learning_Work\01_Learning\Claude_Project\movie_tracker\start.bat'
$sc.WorkingDirectory = 'D:\01_Learning_Work\01_Learning\Claude_Project\movie_tracker'
$sc.IconLocation = 'D:\01_Learning_Work\01_Learning\Claude_Project\movie_tracker\static\img\icon.ico'
$sc.Description = 'Movie Diary'
$sc.WindowStyle = 7
$sc.Save()
Write-Host 'Desktop shortcut: MovieDiary.lnk'
