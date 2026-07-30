package com.personalwebsite.common;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * BusinessException 业务异常单元测试
 */
@DisplayName("BusinessException 业务异常")
class BusinessExceptionTest {

    @Nested
    @DisplayName("构造测试")
    class ConstructorTests {

        @Test
        @DisplayName("code + message 构造：getCode/getMessage 正确")
        void shouldCreateWithCodeAndMessage() {
            BusinessException ex = new BusinessException(400, "参数错误");

            assertEquals(400, ex.getCode());
            assertEquals("参数错误", ex.getMessage());
        }

        @Test
        @DisplayName("code + message + cause 构造：可包装原始异常")
        void shouldCreateWithCause() {
            RuntimeException cause = new RuntimeException("原始错误");
            BusinessException ex = new BusinessException(500, "业务失败", cause);

            assertEquals(500, ex.getCode());
            assertEquals(cause, ex.getCause());
        }
    }
}
