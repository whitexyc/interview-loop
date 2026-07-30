package com.personalwebsite.controller;

import com.personalwebsite.common.CommonResult;
import com.personalwebsite.service.ResumeService;
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
 * ResumeController 单元测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ResumeController 简历接口")
class ResumeControllerTest {

    @Mock
    private ResumeService resumeService;

    @InjectMocks
    private ResumeController resumeController;

    @Nested
    @DisplayName("GET /api/v1/resume")
    class GetResumeTests {

        @Test
        @DisplayName("简历存在时返回 200 + data")
        void shouldReturnResumeWhenExists() {
            ResumeDTO dto = new ResumeDTO();
            dto.setName("张三");
            when(resumeService.getResume()).thenReturn(dto);

            CommonResult<ResumeDTO> result = resumeController.getResume();

            assertEquals(0, result.getCode());
            assertEquals("success", result.getMsg());
            assertNotNull(result.getData());
            assertEquals("张三", result.getData().getName());
        }

        @Test
        @DisplayName("简历不存在时返回 404")
        void shouldReturn404WhenNotExists() {
            when(resumeService.getResume()).thenReturn(null);

            CommonResult<ResumeDTO> result = resumeController.getResume();

            assertEquals(404, result.getCode());
            assertEquals("简历数据不存在", result.getMsg());
            assertNull(result.getData());
        }
    }
}
