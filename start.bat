@echo off
REM ============================================================
REM  一键启动（三服务并行）
REM  - AI 层    :8001  (uvicorn, ai_service/)
REM  - Java 后端 :8080  (spring-boot, backend/)
REM  - 前端     :3001  (vite, frontend/)
REM ============================================================

start "AI-Layer" cmd /k "cd /d %~dp0ai_service && python -m uvicorn main:app --host 0.0.0.0 --port 8001"
start "Java-Backend" cmd /k "cd /d %~dp0backend && java -jar target\personal-website-0.1.0-module-001.jar"
start "Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
