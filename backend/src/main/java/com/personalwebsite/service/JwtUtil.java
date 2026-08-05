package com.personalwebsite.service;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;

/**
 * JWT 工具类
 * <p>HS256 签发与解析；payload: {sub=user_id, username, exp=7天}</p>
 * <p>共享密钥来自配置 jwt.secret（环境变量 APP_JWT_SECRET 覆盖），缺失/过短时服务启动失败（fail-fast）</p>
 */
@Component
public class JwtUtil {

    private static final Logger log = LoggerFactory.getLogger(JwtUtil.class);

    /** HS256 要求密钥至少 256 bits = 32 字节 */
    private static final int MIN_SECRET_BYTES = 32;

    /** 本地开发占位符（application.yml 默认值，与 ai_service/.env 的 PW_JWT_SECRET 同值）——
     *  检测到即告警：生产必须用环境变量 APP_JWT_SECRET 覆盖，不得使用公开占位符 */
    private static final String DEV_PLACEHOLDER_PREFIX = "dev-only-local-jwt-secret";

    private final SecretKey key;
    private final long expireDays;

    /**
     * 构造：校验 secret 长度（HS256 ≥32 字节），不满足则拒绝启动，避免运行时静默降级
     *
     * @param secret     JWT 共享密钥（来自配置 jwt.secret）
     * @param expireDays token 有效期天数
     */
    public JwtUtil(@Value("${jwt.secret}") String secret,
                   @Value("${jwt.expire-days:7}") long expireDays) {
        byte[] keyBytes = secret != null ? secret.getBytes(StandardCharsets.UTF_8) : new byte[0];
        if (keyBytes.length < MIN_SECRET_BYTES) {
            throw new IllegalStateException(
                    "jwt.secret 配置缺失或长度不足（HS256 要求 ≥" + MIN_SECRET_BYTES + " 字节），请通过环境变量 APP_JWT_SECRET 设置");
        }
        if (secret.startsWith(DEV_PLACEHOLDER_PREFIX)) {
            log.warn("当前使用【本地开发占位符】JWT 密钥（{}…）。生产环境必须设置环境变量 APP_JWT_SECRET 覆盖，"
                    + "否则任何可访问仓库的人都知道此密钥、可伪造用户 token。", secret.substring(0, Math.min(16, secret.length())));
        }
        this.key = Keys.hmacShaKeyFor(keyBytes);
        this.expireDays = expireDays;
        log.info("JwtUtil 初始化完成，expireDays={}", expireDays);
    }

    /**
     * 签发 JWT
     *
     * @param userId   用户 ID（写入 sub）
     * @param username 用户名
     * @return JWT 字符串
     */
    public String generateToken(Long userId, String username) {
        Date now = new Date();
        Date expiration = new Date(now.getTime() + expireDays * 24L * 3600 * 1000);
        // 显式指定 HS256：jjwt 0.12 的 signWith(key) 会按密钥长度自动选算法，
        // 64 字节 secret（512 bits）会自动签 HS512，而 Python 端 parse_jwt 仅接受
        // HS256（契约 §3.5）→ 真实 token 被拒、登录身份不解析（Tester 真实 E2E 发现）。
        return Jwts.builder()
                .subject(String.valueOf(userId))
                .claim("username", username)
                .issuedAt(now)
                .expiration(expiration)
                .signWith(key, Jwts.SIG.HS256)
                .compact();
    }

    /**
     * 解析并校验 JWT（非法/过期抛 {@link JwtException}）
     *
     * @param token JWT 字符串
     * @return Claims
     */
    public Claims parseToken(String token) {
        return Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }

    /**
     * 从 Claims 提取用户 ID
     *
     * @param claims 解析后的 Claims
     * @return 用户 ID
     */
    public Long getUserId(Claims claims) {
        return Long.valueOf(claims.getSubject());
    }
}
