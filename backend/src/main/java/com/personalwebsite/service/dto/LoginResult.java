package com.personalwebsite.service.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

/**
 * 登录响应数据：{token, username, user_id}
 * <p>（/api/auth/me 复用本结构，此时 token 为 null 被省略）</p>
 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class LoginResult {

    private String token;

    private String username;

    @JsonProperty("user_id")
    private Long userId;

    private LoginResult(String token, String username, Long userId) {
        this.token = token;
        this.username = username;
        this.userId = userId;
    }

    /** 工厂方法 */
    public static LoginResult of(String token, String username, Long userId) {
        return new LoginResult(token, username, userId);
    }
}
