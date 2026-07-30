package com.personalwebsite.service;

import com.personalwebsite.model.ResumeEntity;
import com.personalwebsite.repository.ResumeRepository;
import com.personalwebsite.service.dto.ResumeDTO;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * ResumeService 单元测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ResumeService 简历业务")
class ResumeServiceTest {

    @Mock
    private ResumeRepository resumeRepository;

    @InjectMocks
    private ResumeService resumeService;

    @Nested
    @DisplayName("getResume()")
    class GetResumeTests {

        @Test
        @DisplayName("简历存在时返回 DTO")
        void shouldReturnDtoWhenResumeExists() {
            ResumeEntity entity = new ResumeEntity();
            entity.setId(1L);
            entity.setName("张三");
            entity.setPhone("13800138000");
            when(resumeRepository.selectById(1L)).thenReturn(entity);

            ResumeDTO dto = resumeService.getResume();

            assertNotNull(dto);
            assertEquals("张三", dto.getName());
            assertEquals("13800138000", dto.getPhone());
        }

        @Test
        @DisplayName("简历不存在时返回 null")
        void shouldReturnNullWhenResumeNotExist() {
            when(resumeRepository.selectById(1L)).thenReturn(null);

            ResumeDTO dto = resumeService.getResume();

            assertNull(dto);
        }
    }

    @Nested
    @DisplayName("initSeedData()")
    class InitSeedDataTests {

        @Test
        @DisplayName("简历已存在时跳过初始化")
        void shouldSkipWhenResumeExists() {
            when(resumeRepository.selectById(1L)).thenReturn(new ResumeEntity());

            resumeService.initSeedData();

            verify(resumeRepository, never()).insert(any());
        }

        @Test
        @DisplayName("简历不存在时插入种子数据")
        void shouldInsertWhenResumeNotExists() {
            when(resumeRepository.selectById(1L)).thenReturn(null);

            resumeService.initSeedData();

            verify(resumeRepository, times(1)).insert(any(ResumeEntity.class));
        }
    }
}
