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

        @Test
        @DisplayName("64 字节生产密钥签发的 token 算法为 HS256（jjwt 自动选算法 bug 回归）")
        void shouldSignHS256WithLongSecret() {
            // 生产 .env PW_JWT_SECRET 为 64 字节（512 bits）；jjwt 0.12 的 signWith(key)
            // 对 ≥512bit 密钥会自动选 HS512，而 Python parse_jwt 仅接受 HS256 →
            // 真实 token 被拒、登录身份不解析（Tester 真实 E2E 发现，跨栈契约失败）。
            // 显式 signWith(key, Jwts.SIG.HS256) 后 header.alg 必须为 HS256。
            String longSecret = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"; // 64 字节
            JwtUtil util64 = new JwtUtil(longSecret, 7);
            String token = util64.generateToken(1L, "eve");

            String header = new String(
                    java.util.Base64.getUrlDecoder().decode(token.split("\\.")[0]),
                    java.nio.charset.StandardCharsets.UTF_8);
            assertTrue(header.contains("\"alg\":\"HS256\""),
                    "token header 应为 HS256，实际: " + header);
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
