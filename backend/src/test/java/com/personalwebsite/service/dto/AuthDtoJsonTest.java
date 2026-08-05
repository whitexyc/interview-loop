package com.personalwebsite.service.dto;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 认证 DTO 序列化测试
 * <p>锁定跨栈契约 JSON key：register→{user_id}，login→{token, username, user_id}</p>
 */
@DisplayName("认证 DTO JSON 序列化（跨栈契约）")
class AuthDtoJsonTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    @DisplayName("RegisterResult 序列化为 {user_id}")
    void shouldSerializeRegisterResult() throws Exception {
        String json = mapper.writeValueAsString(RegisterResult.of(1L));

        assertEquals("{\"user_id\":1}", json);
    }

    @Test
    @DisplayName("LoginResult 序列化为 {token, username, user_id}")
    void shouldSerializeLoginResult() throws Exception {
        String json = mapper.writeValueAsString(LoginResult.of("jwt-token", "alice", 1L));

        assertEquals("{\"token\":\"jwt-token\",\"username\":\"alice\",\"user_id\":1}", json);
    }

    @Test
    @DisplayName("token 为 null 时省略（/api/auth/me 复用场景）")
    void shouldOmitNullToken() throws Exception {
        String json = mapper.writeValueAsString(LoginResult.of(null, "alice", 1L));

        assertEquals("{\"username\":\"alice\",\"user_id\":1}", json);
    }
}
