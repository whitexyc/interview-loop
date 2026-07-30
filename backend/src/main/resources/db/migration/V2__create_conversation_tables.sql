-- V2__create_conversation_tables.sql
-- 聊天会话与消息表

CREATE TABLE IF NOT EXISTS conversations (
    id              BIGSERIAL    PRIMARY KEY,
    title           VARCHAR(200) NOT NULL DEFAULT '新对话',
    message_count   INTEGER      NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE conversations IS '聊天会话表';
COMMENT ON COLUMN conversations.title IS '会话标题（自动从首条用户消息截取前30字）';
COMMENT ON COLUMN conversations.message_count IS '消息数量（冗余字段，PUT时同步更新）';

CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL    PRIMARY KEY,
    conversation_id BIGINT       NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(10)  NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT         NOT NULL,
    sources         JSONB        DEFAULT '[]'::jsonb,
    sort_order      INTEGER      NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_conv_order ON messages (conversation_id, sort_order);

COMMENT ON TABLE messages IS '聊天消息表';
COMMENT ON COLUMN messages.sources IS 'AI 消息的引用来源，用户消息为空数组';
COMMENT ON COLUMN messages.sort_order IS '消息在会话内的排序号（0, 1, 2...）';
