-- V032__create_users.sql
-- 用户表（module-032 JWT 登录体系）

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL    PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL UNIQUE,
    password_hash VARCHAR(100) NOT NULL,
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE users IS '用户表';
COMMENT ON COLUMN users.username IS '登录用户名，唯一';
COMMENT ON COLUMN users.password_hash IS 'BCrypt 密码哈希（不存明文）';
