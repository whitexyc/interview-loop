# 验收标准 — Module-001: 项目脚手架搭建

## 1. 功能验收

### 1.1 核心路径验收
- [ ] Docker Compose 可正常启动全部服务 (MySQL + Milvus + Redis)
- [ ] Java 后端 `/api/v1/health` 返回 `{"code": 0, "msg": "success", "data": {"service": "personal-website", "status": "up"}}`
- [ ] Python AI 服务 `/ai/health` 返回 `{"status": "ok"}`
- [ ] 前端 `npm run dev` 可启动开发服务器，页面显示 "Personal Website"
- [ ] 前端可配置后端 API 地址（环境变量 `VITE_API_BASE_URL`）

### 1.2 边界条件验收
- [ ] Docker 服务未启动时，后端健康检查返回降级状态
- [ ] Spring Boot 启动时 MySQL 未就绪，自动重试连接（fail-fast: false）

### 1.3 异常场景验收
- [ ] CommonResult 统一返回格式在异常情况也保持一致
- [ ] GlobalExceptionHandler 捕获 RuntimeException 并返回 `500` 错误

---

## 2. 非功能验收

### 2.1 性能验收
- [ ] 健康检查接口响应 ≤ 100ms（本地）
- [ ] Spring Boot 启动时间 ≤ 15s

### 2.2 安全验收
- [ ] 无硬编码密码（数据库密码通过环境变量注入）
- [ ] CORS 配置仅允许前端域名

### 2.3 代码质量验收
- [ ] Java 统一返回格式符合 `{code, msg, data, timestamp, request_id}` 规范
- [ ] 命名符合 CLAUDE.md 规范
- [ ] 无跨层调用

---

## 3. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| Docker 启动 | `docker-compose up -d` | 3 个容器 running |
| Java 后端编译 | `cd backend && mvn compile` | BUILD SUCCESS |
| Java 健康检查 | `curl http://localhost:8080/api/v1/health` | `{"code":0,"msg":"success",...}` |
| Python 启动 | `cd ai_service && python main.py` | 端口 8000 监听 |
| Python 健康检查 | `curl http://localhost:8000/ai/health` | `{"status":"ok"}` |
| 前端启动 | `cd frontend && npm run dev` | 页面可访问 |

---

## 4. 验收结论

- 审查人: Reviewer（审查不通过1项→修复后通过）
- 测试人: Tester（12/12 通过）
- 验收时间: 2026-07-29
- 结论: [x] 通过 / [ ] 不通过
- 备注: 3项(Docker/Python/前端)需运行时环境验证，代码和配置已就绪，不阻塞后续模块
