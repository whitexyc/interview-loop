package com.personalwebsite.controller;

import com.personalwebsite.common.CommonResult;
import com.personalwebsite.service.ResumeService;
import com.personalwebsite.service.dto.ResumeDTO;
import org.springframework.web.bind.annotation.*;

/**
 * 简历展示控制器
 */
@RestController
@RequestMapping("/api/v1")
public class ResumeController {

    private final ResumeService resumeService;

    public ResumeController(ResumeService resumeService) {
        this.resumeService = resumeService;
    }

    /**
     * 获取简历完整数据
     */
    @GetMapping("/resume")
    public CommonResult<ResumeDTO> getResume() {
        ResumeDTO resume = resumeService.getResume();
        if (resume == null) {
            return CommonResult.error(404, "简历数据不存在");
        }
        return CommonResult.success(resume);
    }

    /**
     * 更新简历数据
     */
    @PutMapping("/resume")
    public CommonResult<ResumeDTO> updateResume(@RequestBody ResumeDTO dto) {
        ResumeDTO updated = resumeService.updateResume(dto);
        if (updated == null) {
            return CommonResult.error(404, "简历不存在");
        }
        return CommonResult.success(updated);
    }
}
