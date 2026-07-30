package com.personalwebsite.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.personalwebsite.model.MessageEntity;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 消息数据访问层
 */
@Mapper
public interface MessageRepository extends BaseMapper<MessageEntity> {

    /** 按会话 ID 删除所有消息（PUT 全量替换时使用） */
    @Delete("DELETE FROM messages WHERE conversation_id = #{conversationId}")
    int deleteByConversationId(@Param("conversationId") Long conversationId);
}
