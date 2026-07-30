package com.personalwebsite.service.dto;

import com.personalwebsite.model.MessageEntity;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 消息 DTO
 */
@Data
public class MessageDTO {
    private Long id;
    private Long conversationId;
    private String role;
    private String content;
    private List<MessageEntity.SourceRef> sources;
    private Integer sortOrder;
    private LocalDateTime createdAt;

    public static MessageDTO fromEntity(MessageEntity entity) {
        if (entity == null) return null;
        MessageDTO dto = new MessageDTO();
        dto.setId(entity.getId());
        dto.setConversationId(entity.getConversationId());
        dto.setRole(entity.getRole());
        dto.setContent(entity.getContent());
        dto.setSources(entity.getSources());
        dto.setSortOrder(entity.getSortOrder());
        dto.setCreatedAt(entity.getCreatedAt());
        return dto;
    }
}
