package com.personalwebsite.service.dto;

import com.personalwebsite.model.ResumeEntity;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 简历数据传输对象（对外暴露层）
 */
@Data
public class ResumeDTO {
    private Long id;
    private String name;
    private String gender;
    private String phone;
    private String email;
    private String jobIntent;
    private String github;
    private List<ResumeEntity.EducationItem> education;
    private List<String> honors;
    private List<ResumeEntity.SkillItem> skills;
    private List<ResumeEntity.ProjectItem> projects;
    private String selfEvaluation;
    private LocalDateTime updatedAt;

    public static ResumeDTO fromEntity(ResumeEntity entity) {
        if (entity == null) return null;
        ResumeDTO dto = new ResumeDTO();
        dto.setId(entity.getId());
        dto.setName(entity.getName());
        dto.setGender(entity.getGender());
        dto.setPhone(entity.getPhone());
        dto.setEmail(entity.getEmail());
        dto.setJobIntent(entity.getJobIntent());
        dto.setGithub(entity.getGithub());
        dto.setEducation(entity.getEducation());
        dto.setHonors(entity.getHonors());
        dto.setSkills(entity.getSkills());
        dto.setProjects(entity.getProjects());
        dto.setSelfEvaluation(entity.getSelfEvaluation());
        dto.setUpdatedAt(entity.getUpdatedAt());
        return dto;
    }
}
