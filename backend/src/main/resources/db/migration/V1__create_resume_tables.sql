-- V1__create_resume_tables.sql
-- 简历数据表：使用 JSONB 存储结构化数据

CREATE TABLE IF NOT EXISTS resume_profiles (
    id              BIGSERIAL    PRIMARY KEY,
    name            VARCHAR(50)  NOT NULL,
    gender          VARCHAR(10),
    phone           VARCHAR(20),
    email           VARCHAR(100),
    job_intent      VARCHAR(200),
    github          VARCHAR(200),
    education       JSONB        DEFAULT '[]',
    honors          JSONB        DEFAULT '[]',
    skills          JSONB        DEFAULT '[]',
    projects        JSONB        DEFAULT '[]',
    self_evaluation TEXT,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE resume_profiles IS '简历信息表';
COMMENT ON COLUMN resume_profiles.education IS '教育经历（JSONB数组）';
COMMENT ON COLUMN resume_profiles.honors IS '荣誉证书（JSONB数组）';
COMMENT ON COLUMN resume_profiles.skills IS '专业技能（JSONB数组）';
COMMENT ON COLUMN resume_profiles.projects IS '项目经历（JSONB数组）';
