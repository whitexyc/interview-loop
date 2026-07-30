package com.personalwebsite.common;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.time.Instant;
import java.util.UUID;

/**
 * 统一API返回格式
 * <p>所有接口返回此结构，确保前后端交互一致</p>
 *
 * @param <T> data 字段类型
 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class CommonResult<T> {

    /** 状态码：0=成功，非0=失败 */
    private int code;

    /** 状态描述 */
    private String msg;

    /** 响应数据 */
    private T data;

    /** 服务器时间戳（毫秒） */
    private long timestamp;

    /** 请求追踪ID */
    @JsonProperty("request_id")
    private String requestId;

    private CommonResult() {
        this.timestamp = Instant.now().toEpochMilli();
        this.requestId = UUID.randomUUID().toString();
    }

    /** 成功（无数据） */
    public static <T> CommonResult<T> success() {
        CommonResult<T> result = new CommonResult<>();
        result.code = 0;
        result.msg = "success";
        return result;
    }

    /** 成功（有数据） */
    public static <T> CommonResult<T> success(T data) {
        CommonResult<T> result = new CommonResult<>();
        result.code = 0;
        result.msg = "success";
        result.data = data;
        return result;
    }

    /** 失败 */
    public static <T> CommonResult<T> error(int code, String msg) {
        CommonResult<T> result = new CommonResult<>();
        result.code = code;
        result.msg = msg;
        return result;
    }

    /** 失败（带数据） */
    public static <T> CommonResult<T> error(int code, String msg, T data) {
        CommonResult<T> result = new CommonResult<>();
        result.code = code;
        result.msg = msg;
        result.data = data;
        return result;
    }
}
