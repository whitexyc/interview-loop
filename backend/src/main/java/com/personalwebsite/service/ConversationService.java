package com.personalwebsite.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.personalwebsite.common.BusinessException;
import com.personalwebsite.model.ConversationEntity;
import com.personalwebsite.model.MessageEntity;
import com.personalwebsite.repository.ConversationRepository;
import com.personalwebsite.repository.MessageRepository;
import com.personalwebsite.service.dto.ConversationSummaryDTO;
import com.personalwebsite.service.dto.MessageDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 会话业务逻辑
 */
@Service
public class ConversationService {

    private static final Logger log = LoggerFactory.getLogger(ConversationService.class);

    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;

    public ConversationService(ConversationRepository conversationRepository,
                               MessageRepository messageRepository) {
        this.conversationRepository = conversationRepository;
        this.messageRepository = messageRepository;
    }

    /** 列出所有会话，按更新时间倒序 */
    public List<ConversationSummaryDTO> listConversations() {
        List<ConversationEntity> entities = conversationRepository.selectList(
            new LambdaQueryWrapper<ConversationEntity>()
                .orderByDesc(ConversationEntity::getUpdatedAt)
        );
        return entities.stream().map(ConversationSummaryDTO::fromEntity).collect(Collectors.toList());
    }

    /** 创建新会话 */
    public ConversationSummaryDTO createConversation() {
        ConversationEntity entity = new ConversationEntity();
        entity.setTitle("新对话");
        entity.setMessageCount(0);
        conversationRepository.insert(entity);
        log.info("会话已创建: id={}", entity.getId());
        return ConversationSummaryDTO.fromEntity(entity);
    }

    /** 删除会话（CASCADE 自动删除关联消息） */
    @Transactional
    public void deleteConversation(Long id) {
        ConversationEntity entity = conversationRepository.selectById(id);
        if (entity == null) {
            throw new BusinessException(404, "会话不存在");
        }
        messageRepository.deleteByConversationId(id);
        conversationRepository.deleteById(id);
        log.info("会话已删除: id={}", id);
    }

    /** 获取会话的所有消息 */
    public List<MessageDTO> getMessages(Long conversationId) {
        ConversationEntity conv = conversationRepository.selectById(conversationId);
        if (conv == null) {
            throw new BusinessException(404, "会话不存在");
        }
        List<MessageEntity> messages = messageRepository.selectList(
            new LambdaQueryWrapper<MessageEntity>()
                .eq(MessageEntity::getConversationId, conversationId)
                .orderByAsc(MessageEntity::getSortOrder)
        );
        return messages.stream().map(MessageDTO::fromEntity).collect(Collectors.toList());
    }

    /** 全量替换消息（PUT 语义）：事务中删除旧消息 + 批量插入新消息 + 更新计数和标题 */
    @Transactional
    public void saveMessages(Long conversationId, List<MessageDTO> messages) {
        ConversationEntity conv = conversationRepository.selectById(conversationId);
        if (conv == null) {
            throw new BusinessException(404, "会话不存在");
        }

        // 1. 删除旧消息
        messageRepository.deleteByConversationId(conversationId);

        // 2. 批量插入新消息
        if (messages != null && !messages.isEmpty()) {
            List<MessageEntity> entities = new ArrayList<>();
            for (int i = 0; i < messages.size(); i++) {
                MessageDTO dto = messages.get(i);
                MessageEntity entity = new MessageEntity();
                entity.setConversationId(conversationId);
                entity.setRole(dto.getRole());
                entity.setContent(dto.getContent());
                entity.setSources(dto.getSources());
                entity.setSortOrder(i);
                entities.add(entity);
            }
            for (MessageEntity entity : entities) {
                messageRepository.insert(entity);
            }
        }

        // 3. 更新会话元数据
        conv.setMessageCount(messages != null ? messages.size() : 0);
        if ("新对话".equals(conv.getTitle()) && messages != null) {
            for (MessageDTO msg : messages) {
                if ("user".equals(msg.getRole()) && msg.getContent() != null) {
                    String content = msg.getContent().trim();
                    conv.setTitle(content.length() > 30 ? content.substring(0, 30) : content);
                    break;
                }
            }
        }

        conversationRepository.updateById(conv);
        log.info("消息已保存: conversationId={}, count={}", conversationId, conv.getMessageCount());
    }
}
