package com.personalwebsite.common;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * CommonResult 统一返回格式单元测试
 */
@DisplayName("CommonResult 统一返回格式")
class CommonResultTest {

    @Nested
    @DisplayName("成功响应")
    class SuccessTests {

        @Test
        @DisplayName("无数据 success(): code=0, msg=success, data=null")
        void shouldReturnSuccessWithoutData() {
            CommonResult<Void> result = CommonResult.success();

            assertEquals(0, result.getCode());
            assertEquals("success", result.getMsg());
            assertNull(result.getData());
            assertNotNull(result.getRequestId());
            assertTrue(result.getTimestamp() > 0);
        }

        @Test
        @DisplayName("有数据 success(data): 携带数据")
        void shouldReturnSuccessWithData() {
            Map<String, String> data = Map.of("status", "up");
            CommonResult<Map<String, String>> result = CommonResult.success(data);

            assertEquals(0, result.getCode());
            assertEquals("success", result.getMsg());
            assertEquals(data, result.getData());
        }
    }

    @Nested
    @DisplayName("失败响应")
    class ErrorTests {

        @Test
        @DisplayName("error(code, msg): 返回指定错误码和消息")
        void shouldReturnErrorWithCodeAndMsg() {
            CommonResult<Void> result = CommonResult.error(500, "服务器内部错误");

            assertEquals(500, result.getCode());
            assertEquals("服务器内部错误", result.getMsg());
            assertNull(result.getData());
        }

        @Test
        @DisplayName("error(code, msg, data): 携带错误详情")
        void shouldReturnErrorWithData() {
            Map<String, String> detail = Map.of("field", "username", "reason", "required");
            CommonResult<Map<String, String>> result = CommonResult.error(400, "参数错误", detail);

            assertEquals(400, result.getCode());
            assertEquals(detail, result.getData());
        }
    }

    @Nested
    @DisplayName("字段生成")
    class FieldGenerationTests {

        @Test
        @DisplayName("requestId 应自动生成且唯一")
        void shouldGenerateUniqueRequestId() {
            CommonResult<Void> r1 = CommonResult.success();
            CommonResult<Void> r2 = CommonResult.success();

            assertNotNull(r1.getRequestId());
            assertNotNull(r2.getRequestId());
            assertNotEquals(r1.getRequestId(), r2.getRequestId());
        }

        @Test
        @DisplayName("timestamp 应为正整数")
        void shouldGenerateValidTimestamp() {
            CommonResult<Void> result = CommonResult.success();

            assertTrue(result.getTimestamp() > 0);
            // 时间戳应在当前时间 ± 10 秒内
            long now = System.currentTimeMillis();
            assertTrue(Math.abs(now - result.getTimestamp()) < 10_000);
        }
    }
}
