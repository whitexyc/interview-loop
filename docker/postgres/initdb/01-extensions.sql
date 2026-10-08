-- 初始化扩展与知识图谱。
--
-- 说明：docker-entrypoint-initdb.d 下的脚本只在**数据卷为空**时执行一次。
-- 若已有 pgdata 卷，需手动执行或删除卷重建：
--   docker compose down -v && docker compose up -d
--
-- 建表由应用负责（Java 侧 Flyway 迁移 + ai_service 的 database.py），
-- 这里只准备扩展与 AGE 图谱骨架。

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- AGE 需要先 LOAD 才能在会话中使用；扩展本体装在 ag_catalog schema。
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- 图谱名与 ai_service/rag/graph/graph_store.py 的 GRAPH_NAME 保持一致。
-- 用 DO 块守卫，重复执行不报错。
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'knowledge_graph') THEN
        PERFORM ag_catalog.create_graph('knowledge_graph');
    END IF;
END
$$;
