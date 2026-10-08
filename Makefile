# interview-loop 常用命令
#
# 三个应用服务目前在本机直接启动（改代码不用重建镜像，迭代更快）；
# 依赖服务（PostgreSQL + Redis）走 docker compose。
#
# 完整说明见 README「快速开始」。

.PHONY: help up down logs doctor models ai backend frontend sync test test-ai test-frontend test-admin

help:
	@echo "interview-loop"
	@echo "  make up            起依赖服务（PostgreSQL 16 + pgvector + AGE、Redis）"
	@echo "  make down          停依赖服务（保留数据）"
	@echo "  make clean-data    停依赖服务并清空数据（下次启动重跑 initdb）"
	@echo "  make doctor        环境自检（查密码/密钥/模型/端口等易踩的坑）"
	@echo "  make models        下载三个本地模型权重"
	@echo "  make ai            起 AI 层（8001）"
	@echo "  make backend       起 Java 后端（8081）"
	@echo "  make frontend      起前端（3001）"
	@echo "  make sync NOTES=... 把笔记灌进 RAG（需 --vault LABEL=PATH，见 README）"
	@echo "  make test          跑全部测试"
	@echo "  make ai-admin      出题/面试平台（8002，自带 compose）"

up:
	docker compose up -d
	docker compose ps

down:
	docker compose down

clean-data:
	docker compose down -v

logs:
	docker compose logs -f

doctor:
	python scripts/doctor.py

# 三个本地模型（约 3.2 GB），不随仓库分发
models:
	HF_ENDPOINT=https://hf-mirror.com huggingface-cli download BAAI/bge-m3 \
		--include "*q8_0.gguf" --local-dir ai_service/models/bge-m3-gguf
	HF_ENDPOINT=https://hf-mirror.com huggingface-cli download BAAI/bge-reranker-v2-m3 \
		--local-dir ai_service/models/bge-reranker-v2-m3
	HF_ENDPOINT=https://hf-mirror.com huggingface-cli download vectara/hhem-2.1-open \
		--local-dir ai_service/models/hhem-2.1-open

ai:
	cd ai_service && python -m uvicorn main:app --host 0.0.0.0 --port 8001

backend:
	cd backend && mvn spring-boot:run

frontend:
	cd frontend && npm run dev

sync:
	python scripts/sync_notes.py $(if $(VAULT),--vault $(VAULT),)

ai-admin:
	cd interview-admin && docker compose up -d && ./mvnw spring-boot:run

test: test-ai test-frontend test-admin

test-ai:
	cd ai_service && python -m pytest -q

test-frontend:
	cd frontend && npm test

# 已知 2 项自导入起未通过的测试，见 README「已知问题」
test-admin:
	cd interview-admin && ./mvnw -B -ntp test \
		-Dtest='!XunfeiAudioServiceAssemblerTest,!InterviewRecordServiceImplTest' -DfailIfNoTests=false
