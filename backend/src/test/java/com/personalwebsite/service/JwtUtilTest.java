package com.personalwebsite.service;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * JwtUtil 单元测试
 */
@DisplayName("JwtUtil JWT 工具")
class JwtUtilTest {

    private static final String SECRET = "test-secret-key-at-least-32-bytes-long!!";

    private final JwtUtil jwtUtil = new JwtUtil(SECRET, 7);

    @Nested
    @DisplayName("签发与解析")
    class SignAndParseTests {

        @Test
        @DisplayName("签发的 token 可解析出 sub=user_id 与 username")
        void shouldParseGeneratedToken() {
            String token = jwtUtil.generateToken(42L, "alice");

            Claims claims = jwtUtil.parseToken(token);

            assertEquals("42", claims.getSubject());
            assertEquals("alice", claims.get("username", String.class));
            assertEquals(42L, jwtUtil.getUserId(claims));
        }

        @Test
        @DisplayName("payload exp 与 iat 之差约等于 7 天")
        void shouldHaveSevenDayExpiration() {
            String token = jwtUtil.generateToken(1L, "bob");

            Claims claims = jwtUtil.parseToken(token);

            long diffMs = claims.getExpiration().getTime() - claims.getIssuedAt().getTime();
            assertEquals(7L * 24 * 3600 * 1000, diffMs, 5000);
        }
    }

    @Nested
    @DisplayName("异常场景")
    class ErrorTests {

        @Test
        @DisplayName("过期 token 解析抛 ExpiredJwtException")
        void shouldRejectExpiredToken() {
            JwtUtil expiredUtil = new JwtUtil(SECRET, -1);
            String token = expiredUtil.generateToken(1L, "carol");

            assertThrows(ExpiredJwtException.class, () -> expiredUtil.parseToken(token));
        }

        @Test
        @DisplayName("篡改的 token 解析抛 JwtException")
        void shouldRejectTamperedToken() {
            String token = jwtUtil.generateToken(1L, "dave");
            String tampered = token.substring(0, token.length() - 2) + "xx";

            assertThrows(JwtException.class, () -> jwtUtil.parseToken(tampered));
        }

        @Test
        @DisplayName("secret 过短时构造抛 IllegalStateException（fail-fast）")
        void shouldRejectShortSecret() {
            assertThrows(IllegalStateException.class, () -> new JwtUtil("too-short", 7));
        }
    }
}
