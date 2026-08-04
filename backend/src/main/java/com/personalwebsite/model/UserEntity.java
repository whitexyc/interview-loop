package com.personalwebsite.model;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户实体
 * <p>对应 users 表，密码以 BCrypt 哈希存储，不存明文</p>
 */
@Data
@TableName("users")
public class UserEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String username;

    @TableField("password_hash")
    private String passwordHash;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
