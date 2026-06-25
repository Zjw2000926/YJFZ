@echo off
cd /d "D:\大语言模型调用编程\编程\新版\YJFZ"
echo === 预检分诊训练系统 (独立版) ===
echo.
echo 启动后端 (端口 8010)...
start "TriageBackend" cmd /c "cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8010"
timeout /t 3 /nobreak >/dev/null
echo 启动前端 (端口 3010)...
start "TriageFrontend" cmd /c "cd frontend && npx vite --host 127.0.0.1 --port 3010"
timeout /t 5 /nobreak >/dev/null
echo.
echo 访问 http://localhost:3010
echo 默认账号: admin/admin123 (教师) | student1/123456 (学生)
pause
