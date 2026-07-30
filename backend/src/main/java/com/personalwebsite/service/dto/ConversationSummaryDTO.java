package com.personalwebsite.service.dto;

import com.personalwebsite.model.ConversationEntity;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 会话摘要 DTO（列表项）
 */
@Data
public class ConversationSummaryDTO {
    private Long id;
    private String title;
    private Integer messageCount;
    private LocalDateTime updatedAt;

    public static ConversationSummaryDTO fromEntity(ConversationEntity entity) {
        if (entity == null) return null;
        ConversationSummaryDTO dto = new ConversationSummaryDTO();
        dto.setId(entity.getId());
        dto.setTitle(entity.getTitle());
        dto.setMessageCount(entity.getMessageCount());
        dto.setUpdatedAt(entity.getUpdatedAt());
        return dto;
    }
}
