package com.personalwebsite.controller;

import com.personalwebsite.common.CommonResult;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 健康检查控制器
 */
@RestController
@RequestMapping("/api/v1")
public class HealthController {

    /**
     * 健康检查接口，返回服务状态
     */
    @GetMapping("/health")
    public CommonResult<Map<String, String>> health() {
        Map<String, String> status = Map.of(
                "service", "personal-website",
                "status", "up"
        );
        return CommonResult.success(status);
    }
}
