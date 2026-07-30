package com.personalwebsite.service.dto;

import com.personalwebsite.model.ResumeEntity;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * ResumeDTO 转换测试
 */
@DisplayName("ResumeDTO 数据转换")
class ResumeDTOTest {

    @Nested
    @DisplayName("fromEntity()")
    class FromEntityTests {

        @Test
        @DisplayName("Entity 转 DTO 字段映射正确")
        void shouldMapAllFields() {
            ResumeEntity entity = new ResumeEntity();
            entity.setId(1L);
            entity.setName("张三");
            entity.setPhone("13800138000");
            entity.setGithub("https://github.com/whitexyc");
            entity.setSelfEvaluation("热爱技术");

            ResumeDTO dto = ResumeDTO.fromEntity(entity);

            assertEquals(1L, dto.getId());
            assertEquals("张三", dto.getName());
            assertEquals("13800138000", dto.getPhone());
            assertEquals("https://github.com/whitexyc", dto.getGithub());
            assertEquals("热爱技术", dto.getSelfEvaluation());
        }

        @Test
        @DisplayName("Entity 为 null 时返回 null")
        void shouldReturnNullWhenEntityIsNull() {
            assertNull(ResumeDTO.fromEntity(null));
        }
    }
}
