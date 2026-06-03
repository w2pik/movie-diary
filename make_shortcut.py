"""Create desktop shortcut with custom icon"""
import os
import sys

try:
    import pythoncom
    from win32com.client import Dispatch
except ImportError:
    print("Installing pywin32...")
    os.system(f'"{sys.executable}" -m pip install pywin32 --break-system-packages -q')
    import pythoncom
    from win32com.client import Dispatch

shell = Dispatch("WScript.Shell")
desktop = shell.SpecialFolders("Desktop")
shortcut_path = os.path.join(desktop, "MovieDiary.lnk")

shortcut = shell.CreateShortcut(shortcut_path)
shortcut.TargetPath = r"D:\01_Learning_Work\01_Learning\Claude_Project\movie_tracker\start.bat"
shortcut.WorkingDirectory = r"D:\01_Learning_Work\01_Learning\Claude_Project\movie_tracker"
shortcut.IconLocation = r"D:\01_Learning_Work\01_Learning\Claude_Project\movie_tracker\static\img\icon.ico"
shortcut.Description = "Movie Diary"
shortcut.WindowStyle = 7  # minimized
shortcut.Save()

print(f"Desktop shortcut created: {shortcut_path}")
