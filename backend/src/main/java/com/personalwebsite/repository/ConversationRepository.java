package com.personalwebsite.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.personalwebsite.model.ConversationEntity;
import org.apache.ibatis.annotations.Mapper;

/**
 * 会话数据访问层
 */
@Mapper
public interface ConversationRepository extends BaseMapper<ConversationEntity> {
}
