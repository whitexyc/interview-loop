package com.personalwebsite.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.personalwebsite.common.BusinessException;
import com.personalwebsite.model.UserEntity;
import com.personalwebsite.repository.UserRepository;
import com.personalwebsite.service.dto.LoginResult;
import com.personalwebsite.service.dto.RegisterResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

/**
 * 认证业务逻辑
 * <p>注册：用户名唯一校验 + BCrypt 哈希存储；登录：BCrypt 校验 + 签发 JWT</p>
 */
@Service
public class AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthService.class);

    /** 用户名最大长度（与 users.username VARCHAR(64) 对齐） */
    private static final int USERNAME_MAX_LENGTH = 64;

    private final UserRepository userRepository;
    private final JwtUtil jwtUtil;
    private final BCryptPasswordEncoder passwordEncoder;

    public AuthService(UserRepository userRepository, JwtUtil jwtUtil) {
        this.userRepository = userRepository;
        this.jwtUtil = jwtUtil;
        this.passwordEncoder = new BCryptPasswordEncoder();
    }

    /**
     * 注册：用户名唯一校验 + BCrypt 哈希存储
     *
     * @param username 用户名
     * @param password 密码
     * @return 注册结果（含 user_id）
     */
    public RegisterResult register(String username, String password) {
        validateCredentials(username, password);

        boolean exists = userRepository.selectCount(
                new LambdaQueryWrapper<UserEntity>()
                        .eq(UserEntity::getUsername, username)) > 0;
        if (exists) {
            throw new BusinessException(1, "用户名已存在");
        }

        UserEntity entity = new UserEntity();
        entity.setUsername(username);
        entity.setPasswordHash(passwordEncoder.encode(password));
        userRepository.insert(entity);

        log.info("用户注册成功: userId={}, username={}", entity.getId(), username);
        return RegisterResult.of(entity.getId());
    }

    /**
     * 登录：校验 BCrypt 密码并签发 JWT
     *
     * @param username 用户名
     * @param password 密码
     * @return 登录结果（含 token、username、user_id）
     */
    public LoginResult login(String username, String password) {
        validateCredentials(username, password);

        UserEntity entity = userRepository.selectOne(
                new LambdaQueryWrapper<UserEntity>()
                        .eq(UserEntity::getUsername, username));
        if (entity == null || !passwordEncoder.matches(password, entity.getPasswordHash())) {
            // 用户名不存在与密码错误返回同一 message，避免用户枚举
            throw new BusinessException(1, "用户名或密码错误");
        }

        String token = jwtUtil.generateToken(entity.getId(), entity.getUsername());
        log.info("用户登录成功: userId={}, username={}", entity.getId(), username);
        return LoginResult.of(token, entity.getUsername(), entity.getId());
    }

    /** 参数校验：用户名/密码非空且用户名长度合法 */
    private void validateCredentials(String username, String password) {
        if (username == null || username.trim().isEmpty()) {
            throw new BusinessException(1, "用户名不能为空");
        }
        if (password == null || password.isEmpty()) {
            throw new BusinessException(1, "密码不能为空");
        }
        if (username.length() > USERNAME_MAX_LENGTH) {
            throw new BusinessException(1, "用户名长度不能超过 " + USERNAME_MAX_LENGTH + " 字符");
        }
    }
}
