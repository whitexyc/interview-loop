package com.personalwebsite.controller;

import com.personalwebsite.common.CommonResult;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * HealthController 健康检查控制器单元测试
 */
@DisplayName("HealthController 健康检查")
class HealthControllerTest {

    private final HealthController controller = new HealthController();

    @Test
    @DisplayName("health() 应返回服务状态 up")
    void shouldReturnServiceUp() {
        CommonResult<Map<String, String>> result = controller.health();

        assertEquals(0, result.getCode());
        assertEquals("success", result.getMsg());

        Map<String, String> data = result.getData();
        assertNotNull(data);
        assertEquals("personal-website", data.get("service"));
        assertEquals("up", data.get("status"));
    }
}
