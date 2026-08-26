@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

rem 项目根目录（脚本所在目录）
set "PROJECT_DIR=%~dp0"
set "PYTHON=%PROJECT_DIR%venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [错误] 未找到虚拟环境 Python：%PYTHON%
    echo        请先在当前目录重建 venv 并安装依赖。
    pause
    exit /b 1
)

echo ============================================
echo   本地测试页（test_page.html）一键测试
echo   自动起临时服务器 -^> 打开 Edge -^> 跑完整流程
echo   走到"已完成"页自动结束，Ctrl+C 可随时停止
echo ============================================
echo.

rem 透传参数（如 --no-vlm、--port 8000）
"%PYTHON%" "%PROJECT_DIR%test_flow.py" %*

echo.
echo [退出] 测试已结束，按任意键关闭窗口。
pause >nul
