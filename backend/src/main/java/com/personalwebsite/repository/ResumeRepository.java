package com.personalwebsite.repository;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.personalwebsite.model.ResumeEntity;
import org.apache.ibatis.annotations.Mapper;

/**
 * 简历数据访问层
 */
@Mapper
public interface ResumeRepository extends BaseMapper<ResumeEntity> {
}
