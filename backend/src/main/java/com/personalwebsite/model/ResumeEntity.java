package com.personalwebsite.model;

import com.baomidou.mybatisplus.annotation.*;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 简历信息实体
 * <p>对应 resume_profiles 表，JSONB 字段使用 JacksonTypeHandler 自动序列化/反序列化</p>
 */
@Data
@TableName(value = "resume_profiles", autoResultMap = true)
public class ResumeEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String name;
    private String gender;
    private String phone;
    private String email;

    @TableField("job_intent")
    private String jobIntent;

    private String github;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<EducationItem> education;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> honors;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<SkillItem> skills;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<ProjectItem> projects;

    @TableField("self_evaluation")
    private String selfEvaluation;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;

    // ---- 内部类 ----

    @Data
    public static class EducationItem {
        private String school;
        private String major;
        private String gradeYear;
        private String rank;
        private List<String> courses;
    }

    @Data
    public static class SkillItem {
        private String category;
        private List<String> items;
    }

    @Data
    public static class ProjectItem {
        private String name;
        private String role;
        private String time;
        private String description;
        private List<String> highlights;
    }
}
