package com.personalwebsite.controller;

import com.personalwebsite.common.CommonResult;
import com.personalwebsite.service.AuthService;
import com.personalwebsite.service.dto.AuthRequest;
import com.personalwebsite.service.dto.LoginResult;
import com.personalwebsite.service.dto.RegisterResult;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * AuthController 认证控制器单元测试
 */
@DisplayName("AuthController 认证接口")
class AuthControllerTest {

    private final AuthService authService = mock(AuthService.class);
    private final AuthController controller = new AuthController(authService);

    @Test
    @DisplayName("register() 成功返回 code=0 + data.user_id")
    void shouldRegister() {
        when(authService.register("alice", "password123"))
                .thenReturn(RegisterResult.of(1L));

        AuthRequest request = new AuthRequest();
        request.setUsername("alice");
        request.setPassword("password123");

        CommonResult<RegisterResult> result = controller.register(request);

        assertEquals(0, result.getCode());
        assertNotNull(result.getData());
        assertEquals(1L, result.getData().getUserId());
    }

    @Test
    @DisplayName("login() 成功返回 code=0 + data.token/username/user_id")
    void shouldLogin() {
        when(authService.login("alice", "password123"))
                .thenReturn(LoginResult.of("jwt-token", "alice", 1L));

        AuthRequest request = new AuthRequest();
        request.setUsername("alice");
        request.setPassword("password123");

        CommonResult<LoginResult> result = controller.login(request);

        assertEquals(0, result.getCode());
        assertEquals("jwt-token", result.getData().getToken());
        assertEquals("alice", result.getData().getUsername());
        assertEquals(1L, result.getData().getUserId());
    }

    @Test
    @DisplayName("me() 从 request attribute 读取 userId/username")
    void shouldReturnCurrentUser() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("userId", "5");
        request.setAttribute("username", "alice");

        CommonResult<LoginResult> result = controller.me(request);

        assertEquals(0, result.getCode());
        assertEquals(5L, result.getData().getUserId());
        assertEquals("alice", result.getData().getUsername());
        assertNull(result.getData().getToken());
    }
}
