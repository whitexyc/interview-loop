# M15: Redis Query Cache — 验收标准

## 1. 功能
- [ ] 首次查询后缓存写入（日志"检索结果已缓存"）
- [ ] 5 分钟内相同查询命中缓存（日志"检索缓存命中"，跳过检索）
- [ ] TTL 过期后重新检索
- [ ] 不同查询 key 隔离

## 2. 降级
- [ ] Redis 宕机：日志"Redis 缓存不可用"，检索正常
- [ ] Redis 恢复后自动重连

## 3. 代码质量
- [ ] cache.py 有 docstring
- [ ] get/set 均有 try/except
- [ ] config.py 有合理默认值
- [ ] requirements.txt 格式正确
- [ ] python -m py_compile src/cache.py 通过

---

## 验收结论

- 验收人: Tester
- 验收时间: 2026-07-30
- 结论: **通过** ✅
- 全部 11 项验收标准通过。阻塞 bug（自动重连）已修复确认 -- `self._client = None` 在 4 个 catch 块全部存在，`_ensure_client` 增加 `self._connected` 检查。详见 `test-report.md`。
