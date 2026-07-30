package com.personalwebsite.common;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

import static org.junit.jupiter.api.Assertions.*;

/**
 * GlobalExceptionHandler 全局异常处理器单元测试
 * <p>直接测试异常处理方法（不通过 MVC 框架）</p>
 */
@DisplayName("GlobalExceptionHandler 全局异常处理")
class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Nested
    @DisplayName("业务异常处理")
    class BusinessExceptionTests {

        @Test
        @DisplayName("BusinessException → 返回对应错误码和消息")
        void shouldHandleBusinessException() {
            BusinessException ex = new BusinessException(1001, "用户名已存在");
            CommonResult<Void> result = handler.handleBusinessException(ex);

            assertEquals(1001, result.getCode());
            assertEquals("用户名已存在", result.getMsg());
        }
    }

    @Nested
    @DisplayName("运行时异常处理（兜底）")
    class RuntimeExceptionTests {

        @Test
        @DisplayName("RuntimeException → 返回 500 错误")
        void shouldHandleRuntimeException() {
            RuntimeException ex = new RuntimeException("空指针异常");
            CommonResult<Void> result = handler.handleRuntimeException(ex);

            assertEquals(500, result.getCode());
            assertEquals("服务器内部错误，请稍后重试", result.getMsg());
        }
    }

    @Nested
    @DisplayName("通用异常处理")
    class ExceptionTests {

        @Test
        @DisplayName("Exception → 返回 500 错误")
        void shouldHandleException() {
            Exception ex = new Exception("未知错误");
            CommonResult<Void> result = handler.handleException(ex);

            assertEquals(500, result.getCode());
            assertEquals("服务器内部错误", result.getMsg());
        }
    }
}
