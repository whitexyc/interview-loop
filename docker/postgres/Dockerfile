# PostgreSQL 16 + pgvector + Apache AGE
#
# 为什么需要自建镜像：
#   检索链路的三通道之一是知识图谱（Apache AGE），向量通道依赖 pgvector，
#   两者缺一不可，而没有任何官方镜像同时提供。
#   pgvector 有官方镜像（pgvector/pgvector:pg16），AGE 需要从源码编译，
#   因此在 pgvector 官方镜像之上补编 AGE。
#
# 构建：
#   docker compose build postgres
# 或单独构建：
#   docker build -t interview-loop-postgres:16-age1.6 ./docker/postgres
FROM pgvector/pgvector:pg16

# AGE 版本与下载地址（Apache 归档站，URL 稳定可复现）
ARG AGE_VERSION=1.6.0
ARG AGE_URL=https://archive.apache.org/dist/age/PG16/${AGE_VERSION}/apache-age-${AGE_VERSION}-src.tar.gz

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        postgresql-server-dev-16 \
        make \
        g++ \
        flex \
        bison \
        ca-certificates \
        curl; \
    curl -fsSL -o /tmp/age-src.tar.gz "${AGE_URL}"; \
    mkdir -p /tmp/age; \
    tar -xzf /tmp/age-src.tar.gz -C /tmp/age --strip-components=1; \
    make -C /tmp/age; \
    make -C /tmp/age install; \
    rm -rf /tmp/age /tmp/age-src.tar.gz; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# 初始化脚本：建扩展 + 建图谱（与 ai_service 的 rag/graph/graph_store.py 期望一致）
COPY initdb/ /docker-entrypoint-initdb.d/
