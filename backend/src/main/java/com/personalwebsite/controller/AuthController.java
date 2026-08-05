package com.personalwebsite.controller;

import com.personalwebsite.common.CommonResult;
import com.personalwebsite.service.AuthService;
import com.personalwebsite.service.dto.AuthRequest;
import com.personalwebsite.service.dto.LoginResult;
import com.personalwebsite.service.dto.RegisterResult;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;

/**
 * 认证控制器
 * <p>注册 / 登录走 CommonResult；/api/auth/me 受 AuthInterceptor 保护</p>
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    /**
     * 注册
     * <p>成功返回 {code:0, data:{user_id}}；重复用户名返回 code=1 "用户名已存在"</p>
     */
    @PostMapping("/register")
    public CommonResult<RegisterResult> register(@RequestBody AuthRequest request) {
        RegisterResult result = authService.register(request.getUsername(), request.getPassword());
        return CommonResult.success(result);
    }

    /**
     * 登录
     * <p>成功返回 {code:0, data:{token, username, user_id}}；失败返回 code=1 "用户名或密码错误"</p>
     */
    @PostMapping("/login")
    public CommonResult<LoginResult> login(@RequestBody AuthRequest request) {
        LoginResult result = authService.login(request.getUsername(), request.getPassword());
        return CommonResult.success(result);
    }

    /**
     * 当前用户信息（受 AuthInterceptor 保护）
     * <p>userId/username 由拦截器从有效 token 解析后注入 request attribute</p>
     */
    @GetMapping("/me")
    public CommonResult<LoginResult> me(HttpServletRequest request) {
        String userId = (String) request.getAttribute("userId");
        String username = (String) request.getAttribute("username");
        return CommonResult.success(LoginResult.of(null, username, Long.valueOf(userId)));
    }
}
