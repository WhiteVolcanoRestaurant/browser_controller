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

rem 课程 URL：优先使用命令行参数；未传参时由 main.py 读取本地
rem config_platform.py 中的默认主页（不在脚本里硬编码具体平台）
set "COURSE_URL=%~1"

echo ============================================
echo   课程学习自动化脚本启动器
if "%COURSE_URL%"=="" (
    echo   课程 URL：默认主页（config_platform.py 中配置）
) else (
    echo   课程 URL：%COURSE_URL%
)
echo   说明：首次运行会打开 Edge 浏览器，请手动登录
echo         OCR 失败时会尝试 VLM 兜底，请确保 Ollama 已启动
echo         （Ctrl+C 可随时停止）
echo ============================================
echo.

if "%COURSE_URL%"=="" (
    "%PYTHON%" "%PROJECT_DIR%main.py"
) else (
    "%PYTHON%" "%PROJECT_DIR%main.py" "%COURSE_URL%"
)

echo.
echo [退出] 脚本已结束，按任意键关闭窗口。
pause >nul
