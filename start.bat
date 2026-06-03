@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   🎬 电影日记
echo ========================================
echo.
echo   启动中...

set PYTHONIOENCODING=utf-8
start "" http://127.0.0.1:5000

echo   本机浏览器已自动打开
echo   如果需要在手机上访问，请查看命令行窗口显示的地址
echo.
echo   ⚠ 首次使用需允许防火墙弹窗！
echo ========================================
echo.

D:\03_Software\UV_Tool\python_standalone\cpython-3.14.5-windows-x86_64-none\python.exe app.py
pause
