package com.personalwebsite.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.personalwebsite.model.UserEntity;
import org.apache.ibatis.annotations.Mapper;

/**
 * 用户数据访问层
 */
@Mapper
public interface UserRepository extends BaseMapper<UserEntity> {
}
