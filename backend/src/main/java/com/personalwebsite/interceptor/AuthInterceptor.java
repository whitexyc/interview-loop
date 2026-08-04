package com.personalwebsite.interceptor;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.personalwebsite.common.CommonResult;
import com.personalwebsite.service.JwtUtil;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

import java.nio.charset.StandardCharsets;

/**
 * 认证拦截器
 * <p>仅验证受保护接口的 Bearer token 有效性（本项目登录不 gate 公开内容）；</p>
 * <p>校验通过后将 userId/username 注入 request attribute；非法/过期返回 401</p>
 */
@Component
public class AuthInterceptor implements HandlerInterceptor {

    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtUtil jwtUtil;
    private final ObjectMapper objectMapper;

    public AuthInterceptor(JwtUtil jwtUtil, ObjectMapper objectMapper) {
        this.jwtUtil = jwtUtil;
        this.objectMapper = objectMapper;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        // 非 Controller 方法（如静态资源）直接放行
        if (!(handler instanceof HandlerMethod)) {
            return true;
        }

        String authorization = request.getHeader("Authorization");
        if (authorization == null || !authorization.startsWith(BEARER_PREFIX)) {
            writeUnauthorized(response);
            return false;
        }

        try {
            Claims claims = jwtUtil.parseToken(authorization.substring(BEARER_PREFIX.length()));
            request.setAttribute("userId", claims.getSubject());
            request.setAttribute("username", claims.get("username", String.class));
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            writeUnauthorized(response);
            return false;
        }
    }

    /** 写入 401 统一响应体 */
    private void writeUnauthorized(HttpServletResponse response) throws Exception {
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        objectMapper.writeValue(response.getWriter(), CommonResult.error(401, "未授权或登录已过期"));
    }
}
