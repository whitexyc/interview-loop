package com.personalwebsite.service;

import com.personalwebsite.common.BusinessException;
import com.personalwebsite.model.UserEntity;
import com.personalwebsite.repository.UserRepository;
import com.personalwebsite.service.dto.LoginResult;
import com.personalwebsite.service.dto.RegisterResult;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * AuthService 认证业务单元测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AuthService 认证业务")
class AuthServiceTest {

    private static final BCryptPasswordEncoder ENCODER = new BCryptPasswordEncoder();

    @Mock
    private UserRepository userRepository;

    @Mock
    private JwtUtil jwtUtil;

    @InjectMocks
    private AuthService authService;

    @Nested
    @DisplayName("register()")
    class RegisterTests {

        @Test
        @DisplayName("新用户名注册成功，返回 user_id 且密码以 BCrypt 哈希存储")
        void shouldRegisterNewUser() {
            when(userRepository.selectCount(any())).thenReturn(0L);
            // MyBatis-Plus insert 会把自增主键写回实体，mock 需模拟该行为
            doAnswer(invocation -> {
                UserEntity entity = invocation.getArgument(0);
                entity.setId(1L);
                return 1;
            }).when(userRepository).insert(any(UserEntity.class));

            RegisterResult result = authService.register("alice", "password123");

            assertEquals(1L, result.getUserId());
            ArgumentCaptor<UserEntity> captor = ArgumentCaptor.forClass(UserEntity.class);
            verify(userRepository).insert(captor.capture());
            String storedHash = captor.getValue().getPasswordHash();
            assertNotEquals("password123", storedHash);
            assertTrue(ENCODER.matches("password123", storedHash));
        }

        @Test
        @DisplayName("重复用户名注册抛 BusinessException(code=1, 用户名已存在)")
        void shouldRejectDuplicateUsername() {
            when(userRepository.selectCount(any())).thenReturn(1L);

            BusinessException ex = assertThrows(BusinessException.class,
                    () -> authService.register("alice", "password123"));

            assertEquals(1, ex.getCode());
            assertEquals("用户名已存在", ex.getMessage());
            verify(userRepository, never()).insert(any());
        }

        @Test
        @DisplayName("空用户名抛 BusinessException 且不落库")
        void shouldRejectBlankUsername() {
            assertThrows(BusinessException.class,
                    () -> authService.register("", "password123"));

            verify(userRepository, never()).insert(any());
        }
    }

    @Nested
    @DisplayName("login()")
    class LoginTests {

        @Test
        @DisplayName("用户名密码正确返回 token/username/user_id")
        void shouldLoginWithValidCredentials() {
            UserEntity entity = new UserEntity();
            entity.setId(7L);
            entity.setUsername("bob");
            entity.setPasswordHash(ENCODER.encode("password123"));
            when(userRepository.selectOne(any())).thenReturn(entity);
            when(jwtUtil.generateToken(7L, "bob")).thenReturn("jwt-token");

            LoginResult result = authService.login("bob", "password123");

            assertEquals("jwt-token", result.getToken());
            assertEquals("bob", result.getUsername());
            assertEquals(7L, result.getUserId());
        }

        @Test
        @DisplayName("密码错误抛 BusinessException(code=1, 用户名或密码错误)")
        void shouldRejectWrongPassword() {
            UserEntity entity = new UserEntity();
            entity.setId(7L);
            entity.setUsername("bob");
            entity.setPasswordHash(ENCODER.encode("password123"));
            when(userRepository.selectOne(any())).thenReturn(entity);

            BusinessException ex = assertThrows(BusinessException.class,
                    () -> authService.login("bob", "wrong-password"));

            assertEquals(1, ex.getCode());
            assertEquals("用户名或密码错误", ex.getMessage());
            verify(jwtUtil, never()).generateToken(any(), any());
        }

        @Test
        @DisplayName("用户名不存在抛 BusinessException(code=1, 用户名或密码错误)")
        void shouldRejectUnknownUser() {
            when(userRepository.selectOne(any())).thenReturn(null);

            BusinessException ex = assertThrows(BusinessException.class,
                    () -> authService.login("nobody", "password123"));

            assertEquals(1, ex.getCode());
            assertEquals("用户名或密码错误", ex.getMessage());
            verify(jwtUtil, never()).generateToken(any(), any());
        }
    }
}
