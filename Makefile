# Personal Website — Makefile
# Vibe Coding 闭环工作流快捷命令

.PHONY: build test lint docker-up docker-down clean

# ==== 后端 (Java Spring Boot) ====
build:
	cd backend && mvn compile -q

test:
	cd backend && mvn test

lint:
	cd backend && mvn checkstyle:check

# ==== 前端 ====
frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

# ==== AI 服务 ====
ai-install:
	cd ai_service && pip install -r requirements.txt

ai-dev:
	cd ai_service && python main.py

# ==== Docker ====
docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

# ==== 清理 ====
clean:
	cd backend && mvn clean
	rm -rf frontend/dist frontend/node_modules
	rm -rf ai_service/__pycache__ ai_service/.venv
