# 验收标准 — Module-002: 简历数据模型与API

## 1. 功能验收

### 1.1 核心路径验收
- [ ] `GET /api/v1/resume` 返回完整简历数据，code=0
- [ ] 简历数据字段完整（姓名、教育、荣誉、技能、项目经历、自我评价）
- [ ] 所有 JSONB 字段正确反序列化

### 1.2 边界条件验收
- [ ] 简历不存在时返回 404 错误
- [ ] 初始化数据填充后不可重复创建（幂等）

### 1.3 异常场景验收
- [ ] 数据库连接失败时统一返回 500 错误

---

## 2. 非功能验收

### 2.1 性能验收
- [ ] 简历接口响应 ≤ 200ms（本地，无缓存）

### 2.2 代码质量验收
- [ ] 分层正确：Controller → Service → Repository
- [ ] 命名符合 CLAUDE.md 规范
- [ ] API 返回 CommonResult 统一格式
- [ ] 测试覆盖率 ≥ 80%（Service + Controller）

---

## 3. 可运行验证命令

| 验收项 | 命令 | 预期输出 |
|--------|------|----------|
| 编译 | `cd backend && mvn compile -q` | BUILD SUCCESS |
| 单元测试 | `cd backend && mvn test` | All tests passed |
| 接口格式 | `curl http://localhost:8080/api/v1/resume` | `{"code":0,"msg":"success","data":{...}}` |

---

## 4. 验收结论

- 审查人: <待签署>
- 测试人: <待签署>
- 验收时间:
- 结论: [ ] 通过 / [ ] 不通过
