package com.personalwebsite.controller;

import com.personalwebsite.common.CommonResult;
import com.personalwebsite.service.ConversationService;
import com.personalwebsite.service.dto.ConversationSummaryDTO;
import com.personalwebsite.service.dto.MessageDTO;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 会话管理控制器
 */
@RestController
@RequestMapping("/api/v1")
public class ConversationController {

    private final ConversationService conversationService;

    public ConversationController(ConversationService conversationService) {
        this.conversationService = conversationService;
    }

    /** 列出所有会话 */
    @GetMapping("/conversations")
    public CommonResult<List<ConversationSummaryDTO>> listConversations() {
        return CommonResult.success(conversationService.listConversations());
    }

    /** 创建新会话 */
    @PostMapping("/conversations")
    public CommonResult<ConversationSummaryDTO> createConversation() {
        return CommonResult.success(conversationService.createConversation());
    }

    /** 删除会话 */
    @DeleteMapping("/conversations/{id}")
    public CommonResult<Void> deleteConversation(@PathVariable Long id) {
        conversationService.deleteConversation(id);
        return CommonResult.success();
    }

    /** 获取会话消息 */
    @GetMapping("/conversations/{id}/messages")
    public CommonResult<List<MessageDTO>> getMessages(@PathVariable Long id) {
        return CommonResult.success(conversationService.getMessages(id));
    }

    /** 全量保存消息 */
    @PutMapping("/conversations/{id}/messages")
    public CommonResult<Void> saveMessages(@PathVariable Long id, @RequestBody List<MessageDTO> messages) {
        conversationService.saveMessages(id, messages);
        return CommonResult.success();
    }
}
