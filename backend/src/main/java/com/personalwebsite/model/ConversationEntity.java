package com.personalwebsite.model;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 聊天会话实体
 * <p>对应 conversations 表</p>
 */
@Data
@TableName("conversations")
public class ConversationEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String title;

    @TableField("message_count")
    private Integer messageCount;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
