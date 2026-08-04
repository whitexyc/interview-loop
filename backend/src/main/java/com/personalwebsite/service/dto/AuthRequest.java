package com.personalwebsite.service.dto;

import lombok.Data;

/**
 * 认证请求体（注册/登录共用）：{username, password}
 */
@Data
public class AuthRequest {

    private String username;

    private String password;
}
