package com.personalwebsite.service.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

/**
 * 注册响应数据：{user_id}
 */
@Data
public class RegisterResult {

    @JsonProperty("user_id")
    private Long userId;

    private RegisterResult(Long userId) {
        this.userId = userId;
    }

    /** 工厂方法 */
    public static RegisterResult of(Long userId) {
        return new RegisterResult(userId);
    }
}
