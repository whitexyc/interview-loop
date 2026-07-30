package com.personalwebsite.model;

import com.baomidou.mybatisplus.annotation.*;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 聊天消息实体
 * <p>对应 messages 表，JSONB sources 字段使用 JacksonTypeHandler 自动序列化</p>
 */
@Data
@TableName(value = "messages", autoResultMap = true)
public class MessageEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    @TableField("conversation_id")
    private Long conversationId;

    private String role;

    private String content;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<SourceRef> sources;

    @TableField("sort_order")
    private Integer sortOrder;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    // ---- 内部类：JSONB 反序列化目标 ----

    @Data
    public static class SourceRef {
        private Long id;
        private String title;
        private String content;
        private String source;

        @JsonProperty("ref_index")
        private Integer refIndex;
    }
}
