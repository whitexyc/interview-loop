# M9: 聊天记录持久化 — 项目计划

## 元信息

| 字段 | 值 |
|------|-----|
| 模块编号 | M9 |
| 模块名称 | 聊天记录持久化（Chat Persistence） |
| 版本号 | 0.1.0-module-009 |
| 创建日期 | 2026-07-30 |
| 状态 | 规划中 |
| 前置模块 | M8 (知识库面板) |
| 目标 | 将聊天记录从 localStorage 迁移到 PostgreSQL 持久化存储，支持多会话管理 |

---

## 1. 需求概述

### 1.1 当前状态
- ChatPage 使用 `localStorage`（key: `rag_chat_messages`）持久化消息
- 仅支持单会话，无会话切换能力
- 刷新页面时恢复上次消息，但无法查看历史会话

### 1.2 目标状态
- 消息持久化到 PostgreSQL，通过 Java 后端 API 读写
- 支持创建/切换/删除多个会话
- 首次使用自动迁移 localStorage 中的历史消息到数据库
- 消息在 AI 回复完成后自动保存（非流式过程中）

### 1.3 非目标（明确排除）
- 不支持消息编辑/单条删除
- 不支持会话重命名（MVP 阶段，标题自动生成）
- 不支持多用户（单用户个人网站）
- 不支持跨 Tab 实时同步（接受 last-write-wins）
- 不支持分页加载消息（单会话消息量 < 200 条）
- 不引入 WebSocket / 消息推送
- 不引入乐观锁 / 版本冲突检测（单用户场景）

### 1.4 核心约束
- **最小化变更**：不动现有的 UploadPanel、PipelinePanel、CitationModal
- **模式一致**：严格遵循已有 Entity/DTO/Repository/Service/Controller 分层模式
- **表命名一致**：沿用 `resume_profiles` 的 snake_case 命名（不使用 `t_` 前缀）
- **个人网站简化原则**：不引入生产级基础设施（无定时任务、无重试队列、无三级安全网）

---

## 2. 技术方案

### 2.1 整体架构

```
ChatPage (React State)
  │
  ├─ 挂载时: GET /api/v1/conversations ──→ Java Controller ──→ Service ──→ Repository ──→ PostgreSQL
  │           GET /api/v1/conversations/{id}/messages
  │
  ├─ 发送消息: POST /ai/rag/chat/stream ──→ Python AI 后端 (不变)
  │
  ├─ 流完成时: PUT /api/v1/conversations/{id}/messages ──→ Java Controller ──→ Service ──→ PostgreSQL
  │
  └─ 切换会话: PUT 当前会话 → GET 新会话消息
```

**关键设计决策**：
- 前端直接调用 Python AI 后端做流式聊天（保持现有路径不变）
- 前端通过 Java 后端 API 做会话和消息的 CRUD（Java 有数据库访问能力）
- 消息保存使用 **PUT 全量替换** 模式：前端发送完整消息数组，后端在事务中 delete-all + batch-insert
- 保存时机：**仅在流式回复完成后**保存，不在流式过程中保存（避免半截消息入库）

### 2.2 数据库设计

#### DDL: V2__create_conversation_tables.sql

```sql
-- V2__create_conversation_tables.sql
-- 聊天会话与消息表

CREATE TABLE IF NOT EXISTS conversations (
    id              BIGSERIAL    PRIMARY KEY,
    title           VARCHAR(200) NOT NULL DEFAULT '新对话',
    message_count   INTEGER      NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE conversations IS '聊天会话表';
COMMENT ON COLUMN conversations.title IS '会话标题（自动从首条用户消息截取前30字）';
COMMENT ON COLUMN conversations.message_count IS '消息数量（冗余字段，PUT 时同步更新）';

CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL    PRIMARY KEY,
    conversation_id BIGINT       NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(10)  NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT         NOT NULL,
    sources         JSONB        DEFAULT '[]'::jsonb,
    sort_order      INTEGER      NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_conv_order ON messages (conversation_id, sort_order);

COMMENT ON TABLE messages IS '聊天消息表';
COMMENT ON COLUMN messages.sources IS 'AI 消息的引用来源，用户消息为空数组';
COMMENT ON COLUMN messages.sort_order IS '消息在会话内的排序号（0, 1, 2...）';
```

**DDL 设计说明**：
- 表名使用 snake_case（`conversations`, `messages`），与现有 `resume_profiles` 一致
- `JSONB DEFAULT '[]'::jsonb` 与现有表（education/honors/skills/projects 均为 JSONB DEFAULT '[]'）一致
- `ON DELETE CASCADE` 外键确保删除会话时自动清理消息——不需要定时清理任务
- 不引入 `deleted` 逻辑删除字段（遵循个人网站简化原则，硬删除即可）
- `messages` 表无 `updated_at`（消息在 PUT-replace 模型下不可变——删除后重建，不会原地更新）
- 不引入 `version` 乐观锁字段（单用户网站，last-write-wins 即可）

### 2.3 Java 后端设计

#### 2.3.1 实体类

**MessageEntity.java**（新建 `model/MessageEntity.java`）：
```java
@Data
@TableName(value = "messages", autoResultMap = true)
public class MessageEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long conversationId;

    private String role;

    private String content;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<SourceRef> sources;

    private Integer sortOrder;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    // ---- 内部类：JSONB 反序列化目标 ----
    @Data
    public static class SourceRef {
        private Long id;
        private String title;
        private String content;
        private String source;
        @JsonProperty("ref_index")
        private Integer refIndex;
    }
}
```

**ConversationEntity.java**（新建 `model/ConversationEntity.java`）：
```java
@Data
@TableName("conversations")
public class ConversationEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String title;

    private Integer messageCount;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
```

**关键注意点**（来自设计审查发现的问题）：
1. `@TableName(autoResultMap = true)` 必须标注在 `MessageEntity` 上，否则 `JacksonTypeHandler` 不生效——JSONB 字段会返回 `PGobject` 导致 `ClassCastException`
2. `@TableField(fill = FieldFill.INSERT)` 必须标注在 `createdAt` 上，`@TableField(fill = FieldFill.INSERT_UPDATE)` 标注在 `updatedAt` 上——现有 `MyBatisPlusConfig` 的 `strictInsertFill/strictUpdateFill` 只对标注了 `fill` 的字段生效
3. `SourceRef` 使用 `@JsonProperty("ref_index")` 保持与前端 `SourceItem.ref_index` 的 JSON 序列化兼容（Python 后端输出的是 `ref_index`）
4. `@Mapper` 注解在 Repository 接口上必须标注（项目未启用 `@MapperScan`）

#### 2.3.2 DTO

**ConversationSummaryDTO.java**（新建 `service/dto/ConversationSummaryDTO.java`）：
```java
@Data
public class ConversationSummaryDTO {
    private Long id;
    private String title;
    private Integer messageCount;
    private LocalDateTime updatedAt;

    public static ConversationSummaryDTO fromEntity(ConversationEntity entity) {
        if (entity == null) return null;
        ConversationSummaryDTO dto = new ConversationSummaryDTO();
        dto.setId(entity.getId());
        dto.setTitle(entity.getTitle());
        dto.setMessageCount(entity.getMessageCount());
        dto.setUpdatedAt(entity.getUpdatedAt());
        return dto;
    }
}
```

**MessageDTO.java**（新建 `service/dto/MessageDTO.java`）：
```java
@Data
public class MessageDTO {
    private Long id;
    private Long conversationId;
    private String role;
    private String content;
    private List<MessageEntity.SourceRef> sources;
    private Integer sortOrder;
    private LocalDateTime createdAt;

    public static MessageDTO fromEntity(MessageEntity entity) {
        if (entity == null) return null;
        MessageDTO dto = new MessageDTO();
        dto.setId(entity.getId());
        dto.setConversationId(entity.getConversationId());
        dto.setRole(entity.getRole());
        dto.setContent(entity.getContent());
        dto.setSources(entity.getSources());
        dto.setSortOrder(entity.getSortOrder());
        dto.setCreatedAt(entity.getCreatedAt());
        return dto;
    }
}
```

**设计说明**：严格遵循现有 `ResumeDTO.fromEntity()` 模式，每个 DTO 提供静态工厂方法，不使用 `Map<String, Object>`。

#### 2.3.3 Repository

**ConversationRepository.java**（新建）：
```java
@Mapper
public interface ConversationRepository extends BaseMapper<ConversationEntity> {
}
```

**MessageRepository.java**（新建）：
```java
@Mapper
public interface MessageRepository extends BaseMapper<MessageEntity> {

    @Delete("DELETE FROM messages WHERE conversation_id = #{conversationId}")
    int deleteByConversationId(@Param("conversationId") Long conversationId);

    @Select("SELECT * FROM messages WHERE conversation_id = #{conversationId} ORDER BY sort_order ASC")
    List<MessageEntity> selectByConversationId(@Param("conversationId") Long conversationId);
}
```

**设计说明**：
- 遵循现有 `ResumeRepository` 模式：接口 + `extends BaseMapper` + `@Mapper`
- `deleteByConversationId` 和 `selectByConversationId` 使用 MyBatis 注解（简单 SQL，不需要 XML mapper），避免引入 XML mapper 这一项目尚无先例的模式
- MyBatis-Plus 内置的 `saveBatch()` 用于批量插入，不需要自定义 XML

#### 2.3.4 Service

**ConversationService.java**（新建）：
```java
@Service
public class ConversationService {
    private static final Logger log = LoggerFactory.getLogger(ConversationService.class);

    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;

    public ConversationService(ConversationRepository conversationRepository,
                               MessageRepository messageRepository) {
        this.conversationRepository = conversationRepository;
        this.messageRepository = messageRepository;
    }

    /** 列出所有会话，按更新时间倒序 */
    public List<ConversationSummaryDTO> listConversations() {
        List<ConversationEntity> entities = conversationRepository.selectList(
            new LambdaQueryWrapper<ConversationEntity>()
                .orderByDesc(ConversationEntity::getUpdatedAt)
        );
        return entities.stream().map(ConversationSummaryDTO::fromEntity).collect(Collectors.toList());
    }

    /** 创建新会话 */
    public ConversationSummaryDTO createConversation() {
        ConversationEntity entity = new ConversationEntity();
        entity.setTitle("新对话");
        entity.setMessageCount(0);
        conversationRepository.insert(entity);
        return ConversationSummaryDTO.fromEntity(entity);
    }

    /** 删除会话（CASCADE 自动删除关联消息） */
    @Transactional
    public void deleteConversation(Long id) {
        ConversationEntity entity = conversationRepository.selectById(id);
        if (entity == null) {
            throw new BusinessException(404, "会话不存在");
        }
        // 先删消息再删会话（双保险，FK CASCADE 兜底）
        messageRepository.deleteByConversationId(id);
        conversationRepository.deleteById(id);
        log.info("会话已删除: id={}", id);
    }

    /** 获取会话的所有消息 */
    public List<MessageDTO> getMessages(Long conversationId) {
        ConversationEntity conv = conversationRepository.selectById(conversationId);
        if (conv == null) {
            throw new BusinessException(404, "会话不存在");
        }
        List<MessageEntity> messages = messageRepository.selectByConversationId(conversationId);
        return messages.stream().map(MessageDTO::fromEntity).collect(Collectors.toList());
    }

    /** 全量替换消息（PUT 语义）：事务中删除旧消息 + 批量插入新消息 + 更新计数和标题 */
    @Transactional
    public void saveMessages(Long conversationId, List<MessageDTO> messages) {
        ConversationEntity conv = conversationRepository.selectById(conversationId);
        if (conv == null) {
            throw new BusinessException(404, "会话不存在");
        }

        // 1. 删除旧消息
        messageRepository.deleteByConversationId(conversationId);

        // 2. 批量插入新消息
        if (messages != null && !messages.isEmpty()) {
            List<MessageEntity> entities = new ArrayList<>();
            for (int i = 0; i < messages.size(); i++) {
                MessageDTO dto = messages.get(i);
                MessageEntity entity = new MessageEntity();
                entity.setConversationId(conversationId);
                entity.setRole(dto.getRole());
                entity.setContent(dto.getContent());
                entity.setSources(dto.getSources());
                entity.setSortOrder(i);
                entities.add(entity);
            }
            messageRepository.insert(entities); // MyBatis-Plus saveBatch 内部实现
        }

        // 3. 更新会话元数据
        conv.setMessageCount(messages != null ? messages.size() : 0);

        // 自动标题：如果标题还是默认值，取第一条用户消息的前30字
        if ("新对话".equals(conv.getTitle()) && messages != null) {
            for (MessageDTO msg : messages) {
                if ("user".equals(msg.getRole()) && msg.getContent() != null) {
                    String content = msg.getContent().trim();
                    conv.setTitle(content.length() > 30 ? content.substring(0, 30) : content);
                    break;
                }
            }
        }

        conversationRepository.updateById(conv);
        log.info("消息已保存: conversationId={}, count={}", conversationId, conv.getMessageCount());
    }
}
```

**设计说明**：
- `@Transactional` 确保 delete + insert + update 原子性：消息和计数不会不一致
- 标题自动生成使用 `"新对话".equals(title)` 精确匹配默认值，避免覆盖用户手动修改的标题（如后续支持会话重命名，此逻辑仍安全）
- `messageRepository.insert(entities)` 使用 MyBatis-Plus 内置批量插入（底层是循环 `insert(entity)`，对 <200 条消息性能足够）
- 错误处理遵循现有模式：`BusinessException(404, ...)` 经 `GlobalExceptionHandler` 转换为 `CommonResult.error(404, ...)`
- 不使用 `Map<String, Object>` 做返回值——统一使用类型安全的 DTO

#### 2.3.5 Controller

**ConversationController.java**（新建）：
```java
@RestController
@RequestMapping("/api/v1")
public class ConversationController {

    private final ConversationService conversationService;

    public ConversationController(ConversationService conversationService) {
        this.conversationService = conversationService;
    }

    /** 列出会话 */
    @GetMapping("/conversations")
    public CommonResult<List<ConversationSummaryDTO>> listConversations() {
        return CommonResult.success(conversationService.listConversations());
    }

    /** 创建会话 */
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
```

**设计说明**：完全遵循现有 `ResumeController` 的 RestController + CommonResult 模式。

### 2.4 前端设计

#### 2.4.1 新增文件

**`frontend/src/types/conversation.ts`**（新建）：
```typescript
/** 会话摘要（列表项） */
export interface ConversationInfo {
  id: number;
  title: string;
  messageCount: number;
  updatedAt: string;
}

/** 服务端消息格式（含 DB 元数据） */
export interface MessageDTO {
  id: number;
  conversationId: number;
  role: 'user' | 'assistant';
  content: string;
  sources: SourceItem[];
  sortOrder: number;
  createdAt: string;
}
```

**`frontend/src/services/conversationService.ts`**（新建）：
```typescript
import axios from 'axios';
import type { ApiResponse } from '../types/api';
import type { ConversationInfo, MessageDTO } from '../types/conversation';

const http = axios.create({
  baseURL: '/api',
  timeout: 10000,
});

/** 列出所有会话 */
export async function listConversations(): Promise<ConversationInfo[]> {
  const response = await http.get<ApiResponse<ConversationInfo[]>>('/v1/conversations');
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '获取会话列表失败');
  return body.data || [];
}

/** 创建新会话 */
export async function createConversation(): Promise<ConversationInfo> {
  const response = await http.post<ApiResponse<ConversationInfo>>('/v1/conversations');
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '创建会话失败');
  return body.data!;
}

/** 删除会话 */
export async function deleteConversation(id: number): Promise<void> {
  const response = await http.delete<ApiResponse<unknown>>(`/v1/conversations/${id}`);
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '删除会话失败');
}

/** 获取会话消息 */
export async function getMessages(conversationId: number): Promise<MessageDTO[]> {
  const response = await http.get<ApiResponse<MessageDTO[]>>(`/v1/conversations/${conversationId}/messages`);
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '获取消息失败');
  return body.data || [];
}

/** 全量保存消息（PUT 替换） */
export async function saveMessages(conversationId: number, messages: MessageDTO[]): Promise<void> {
  const response = await http.put<ApiResponse<unknown>>(`/v1/conversations/${conversationId}/messages`, messages);
  const body = response.data;
  if (body.code !== 0) throw new Error(body.msg || '保存消息失败');
}
```

**设计说明**：完全遵循现有 `resumeService.ts` 的 Axios + `ApiResponse<T>` + `code !== 0` 错误检查模式。

#### 2.4.2 修改文件

**`frontend/src/pages/ChatPage.tsx`**（修改）：

主要变更：
1. **移除 localStorage 持久化**（删除 `STORAGE_KEY` 常量、两个 `useEffect`）
2. **添加会话状态**：`activeConversationId`, `conversations`
3. **添加会话选择器**：聊天区域顶部的下拉选择器 + 新建/删除按钮
4. **添加保存逻辑**：流式回复完成后自动 PUT 保存
5. **添加加载逻辑**：挂载时加载会话列表，选择会话时加载消息
6. **修复 handleRetry 重复消息 bug**：重试时移除失败的消息对，而非追加
7. **添加 localStorage 迁移**：首次加载时如果 DB 为空且 localStorage 有数据，自动创建会话并导入

具体修改点：

**A. 类型调整**：将本地 `MessageItem` 接口替换为从 `conversation.ts` 导入的 `MessageDTO`（`ChatMessage` 组件只用到 `role/content/sources`，`MessageDTO` 包含这些字段，向后兼容）。

**B. 状态新增**：
```typescript
const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
const [conversations, setConversations] = useState<ConversationInfo[]>([]);
```

**C. 挂载逻辑**（替换原有 localStorage 恢复 effect）：
```typescript
useEffect(() => {
  (async () => {
    try {
      const list = await listConversations();
      if (list.length > 0) {
        setConversations(list);
        // 选中最近更新的会话
        const msgs = await getMessages(list[0].id);
        setActiveConversationId(list[0].id);
        setMessages(msgs);
      } else {
        // 尝试从 localStorage 迁移
        const saved = localStorage.getItem('rag_chat_messages');
        if (saved) {
          try {
            const parsed = JSON.parse(saved);
            if (Array.isArray(parsed) && parsed.length > 0) {
              const conv = await createConversation();
              // 转换为 MessageDTO 格式保存
              const dtos = parsed.map((m, i) => ({ ...m, conversationId: conv.id, sortOrder: i }));
              await saveMessages(conv.id, dtos);
              localStorage.removeItem('rag_chat_messages');
              setConversations([conv]);
              setActiveConversationId(conv.id);
              setMessages(dtos);
              return;
            }
          } catch { /* 迁移失败则创建空会话 */ }
        }
        // 创建首个空会话
        const conv = await createConversation();
        setConversations([conv]);
        setActiveConversationId(conv.id);
      }
    } catch (err) {
      setError('加载会话失败: ' + (err instanceof Error ? err.message : ''));
    }
  })();
}, []);
```

**D. 保存逻辑**（在 `doSend` 流完成后调用）：
```typescript
// 在 doSend 的 try 块末尾（setMessages 更新 sources 之后）：
if (activeConversationId) {
  // 获取最新的 messages 状态（通过函数式 setState 回调无法在 async 中获取最新值，
  // 所以使用 ref 同步最新 messages）
  const latestMessages = messagesRef.current;
  const dtos = latestMessages.map((m, i) => ({
    conversationId: activeConversationId,
    role: m.role,
    content: m.content,
    sources: m.sources || [],
    sortOrder: i,
  }));
  saveMessages(activeConversationId, dtos).catch((e) => {
    console.error('保存消息失败:', e);
  });
}
```

> **关于保存时机的补充说明**：
> - 使用 `useRef` 保持 messages 的最新引用（`messagesRef.current = messages`），在流完成后读取
> - `saveMessages` 是 fire-and-forget（.catch 只打 log），不阻塞 UI
> - 保存失败时消息仍在 React 内存中，下次成功保存时会覆盖
> - 不在流式过程中保存（`loading === true` 时跳过），避免半截 assistant 消息入库

**E. 会话切换逻辑**：
```typescript
const handleSelectConversation = useCallback(async (id: number) => {
  if (id === activeConversationId) return;
  // 先保存当前会话
  if (activeConversationId && messages.length > 0) {
    const dtos = messages.map((m, i) => ({
      conversationId: activeConversationId,
      role: m.role,
      content: m.content,
      sources: m.sources || [],
      sortOrder: i,
    }));
    try { await saveMessages(activeConversationId, dtos); } catch { /* 忽略保存失败 */ }
  }
  // 加载目标会话
  try {
    const msgs = await getMessages(id);
    setActiveConversationId(id);
    setMessages(msgs);
    setError(null);
  } catch (err) {
    setError('加载消息失败: ' + (err instanceof Error ? err.message : ''));
  }
}, [activeConversationId, messages]);
```

**F. 会话选择器 UI**（添加到右栏聊天区域顶部，消息列表上方）：
```tsx
{/* 会话选择器 */}
<div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: '#fff', borderRadius: 12, marginBottom: 8, border: '1px solid rgba(226,232,240,0.6)' }}>
  <Select
    value={activeConversationId}
    onChange={handleSelectConversation}
    style={{ flex: 1 }}
    options={conversations.map(c => ({ value: c.id, label: c.title }))}
    placeholder="选择对话"
  />
  <Button size="small" onClick={handleNewConversation} icon={<PlusOutlined />}>新建</Button>
  <Popconfirm title="确定删除此对话？" onConfirm={handleDeleteConversation} okText="删除" cancelText="取消">
    <Button size="small" danger disabled={conversations.length <= 1}>删除</Button>
  </Popconfirm>
</div>
```

**G. handleRetry 修复**（替换现有 append 逻辑为 replace 逻辑）：
```typescript
// 旧代码（有 bug）:
// setMessages((prev) => [...prev, { role: 'user', content: query }, { role: 'assistant', content: '' }]);
// 新代码:
setMessages((prev) => {
  const cleaned = [...prev];
  // 移除最后一对 user+assistant（失败的消息对）
  if (cleaned.length >= 2 &&
      cleaned[cleaned.length - 2].role === 'user' &&
      cleaned[cleaned.length - 1].role === 'assistant') {
    cleaned.splice(cleaned.length - 2, 2);
  }
  return [...cleaned, { role: 'user', content: query }, { role: 'assistant', content: '' }];
});
```

### 2.5 API 合约

| 方法 | 路径 | 请求体 | 响应体 | 说明 |
|------|------|--------|--------|------|
| GET | `/api/v1/conversations` | — | `CommonResult<ConversationSummaryDTO[]>` | 按 updatedAt 倒序 |
| POST | `/api/v1/conversations` | — | `CommonResult<ConversationSummaryDTO>` | 创建标题为"新对话"的空会话 |
| DELETE | `/api/v1/conversations/{id}` | — | `CommonResult<Void>` | CASCADE 删除关联消息 |
| GET | `/api/v1/conversations/{id}/messages` | — | `CommonResult<MessageDTO[]>` | 按 sortOrder 升序 |
| PUT | `/api/v1/conversations/{id}/messages` | `MessageDTO[]` | `CommonResult<Void>` | 全量替换，事务保证原子性 |

**MessageDTO 请求体格式**（PUT 时前端发送的最小字段集）：
```json
[
  {"role": "user", "content": "我的学习情况", "sources": [], "conversationId": 1, "sortOrder": 0},
  {"role": "assistant", "content": "根据您的简历...", "sources": [{"id": 1, "title": "...", "content": "...", "source": "resume", "ref_index": 1}], "conversationId": 1, "sortOrder": 1}
]
```

---

## 3. 文件清单

### 新建文件（13 个）

| # | 文件路径 | 用途 |
|---|----------|------|
| 1 | `backend/src/main/resources/db/migration/V2__create_conversation_tables.sql` | DDL：conversations + messages 表 |
| 2 | `backend/src/main/java/com/personalwebsite/model/ConversationEntity.java` | 会话实体 |
| 3 | `backend/src/main/java/com/personalwebsite/model/MessageEntity.java` | 消息实体（含 SourceRef 内部类） |
| 4 | `backend/src/main/java/com/personalwebsite/service/dto/ConversationSummaryDTO.java` | 会话摘要 DTO |
| 5 | `backend/src/main/java/com/personalwebsite/service/dto/MessageDTO.java` | 消息 DTO |
| 6 | `backend/src/main/java/com/personalwebsite/repository/ConversationRepository.java` | 会话数据访问 |
| 7 | `backend/src/main/java/com/personalwebsite/repository/MessageRepository.java` | 消息数据访问 |
| 8 | `backend/src/main/java/com/personalwebsite/service/ConversationService.java` | 会话业务逻辑 |
| 9 | `backend/src/main/java/com/personalwebsite/controller/ConversationController.java` | 会话 REST 控制器 |
| 10 | `backend/src/test/java/com/personalwebsite/service/ConversationServiceTest.java` | 服务层单元测试 |
| 11 | `backend/src/test/java/com/personalwebsite/controller/ConversationControllerTest.java` | 控制器层单元测试 |
| 12 | `frontend/src/types/conversation.ts` | 前端会话类型定义 |
| 13 | `frontend/src/services/conversationService.ts` | 前端会话 API 服务 |

### 修改文件（1 个）

| # | 文件路径 | 变更内容 |
|---|----------|----------|
| 14 | `frontend/src/pages/ChatPage.tsx` | 移除 localStorage、添加会话管理、添加自动保存、修复 handleRetry bug |

### 不修改的文件

- `backend/src/main/resources/application.yml` — 不需要变更（Flyway 自动发现 V2 迁移）
- `frontend/src/components/AppLayout.tsx` — 布局不变（会话选择器内嵌在 ChatPage 内）
- `frontend/src/services/ragService.ts` — 流式聊天路径不变
- `frontend/src/types/rag.ts` — SourceItem 类型不变（MessageEntity.SourceRef 通过 @JsonProperty 保持 JSON 兼容）
- `frontend/src/components/ChatMessage.tsx` — 接收的 role/content/sources 字段不变
- `frontend/src/components/PipelinePanel.tsx` — 不涉及
- `frontend/src/components/UploadPanel.tsx` — 不涉及

---

## 4. 实施步骤

### 步骤 1：DDL 迁移
- 创建 `V2__create_conversation_tables.sql`
- 启动应用，Flyway 自动执行迁移
- **验证**：数据库中 `conversations` 和 `messages` 表已创建，`flyway_schema_history` 有 V2 记录

### 步骤 2：后端实体 + DTO
- 创建 `ConversationEntity.java`、`MessageEntity.java`（含 `SourceRef` 内部类）
- 创建 `ConversationSummaryDTO.java`、`MessageDTO.java`（含 `fromEntity()`）
- **验证**：`mvn compile` 通过，无编译错误

### 步骤 3：后端 Repository
- 创建 `ConversationRepository.java`、`MessageRepository.java`
- **验证**：Spring 启动无 Bean 注入错误

### 步骤 4：后端 Service
- 创建 `ConversationService.java`（list/create/delete/getMessages/saveMessages）
- **验证**：编写并运行 `ConversationServiceTest`
  - `testCreateConversation`：创建后 title="新对话", messageCount=0
  - `testSaveMessages`：保存后消息计数正确，按 sortOrder 排序
  - `testDeleteConversation`：删除后消息表无孤儿记录
  - `testAutoTitle`：首条用户消息自动生成标题（≤30字）

### 步骤 5：后端 Controller
- 创建 `ConversationController.java`
- **验证**：编写并运行 `ConversationControllerTest`
  - `testListConversations`：GET 返回 200 + 会话列表
  - `testCreateConversation`：POST 返回 200 + 新会话
  - `testDeleteConversation`：DELETE 返回 200
  - `testGetAndSaveMessages`：PUT 保存后 GET 返回一致数据

### 步骤 6：前端类型 + 服务
- 创建 `conversation.ts`（类型定义）
- 创建 `conversationService.ts`（API 调用）
- **验证**：`npm run build` 通过（TypeScript 编译）

### 步骤 7：前端 ChatPage 重构
- 移除 localStorage 持久化代码（两个 useEffect）
- 添加会话状态（conversations, activeConversationId）
- 添加挂载加载逻辑（含 localStorage → DB 迁移）
- 添加会话选择器 UI（Select + 新建 + 删除按钮，位于聊天区域顶部）
- 在 `doSend` 流完成后调用 `saveMessages()`
- 在 `handleSelectConversation` 中先保存当前会话再加载新会话
- 修复 `handleRetry` 的重复消息 bug
- **验证**：
  - 首次加载：创建空会话
  - 发送消息：流式回复后自动保存，刷新页面消息仍在
  - 切换会话：消息正确切换，原会话已保存
  - 新建会话：出现空聊天区
  - 删除会话：当前会话被删除，自动切换到下一个
  - 重试失败消息：不产生重复消息对
  - localStorage 迁移：如果 DB 为空但 localStorage 有数据，自动导入

### 步骤 8：集成验证（端到端）
- 启动后端 + 前端 + PostgreSQL
- 完整流程测试：
  1. 打开 /chat → 自动创建空会话
  2. 发送 3 轮对话 → 验证消息实时展示 + 自动保存
  3. 刷新页面 → 验证消息恢复
  4. 新建会话 → 验证空聊天区
  5. 切换回旧会话 → 验证消息正确
  6. 删除会话 → 验证被删除，列表更新
  7. 模拟 localStorage 迁移 → 清空 DB，设置 localStorage，刷新页面，验证消息被导入

---

## 5. 风险与应对

| 风险 | 严重度 | 应对措施 |
|------|--------|----------|
| Flyway V2 迁移跳过（flyway_schema_history 无 V1 记录） | 高 | 检查 `application.yml` Flyway 自动配置是否启用；若 flyway_schema_history 表不存在，Flyway 会自动 baseline |
| `JacksonTypeHandler` 不生效（忘记 `autoResultMap = true`） | 高 | 在步骤 2 验证阶段编写测试，查询含 sources 的消息并断言 `List<SourceRef>` 非空 |
| `@TableField(fill)` 缺失导致 `createdAt`/`updatedAt` 为 null | 中 | 在步骤 4 单元测试中断言 `createdAt` 和 `updatedAt` 非 null |
| 会话自动创建竞态（两个 Tab 同时创建） | 低 | 个人网站实际不会同时打开两个 Tab；即便发生，多一个空会话无伤大雅 |
| PUT 保存失败导致消息丢失（刷新后消失） | 低 | `.catch(console.error)` 不阻塞 UI；下次成功保存会覆盖；消息仍在 React 内存中 |
| `SourceRef.refIndex` JSON 序列化不一致（`ref_index` vs `refIndex`） | 中 | 在 `MessageEntity.SourceRef` 上使用 `@JsonProperty("ref_index")` 显式指定 |
| 流式过程中关闭标签页导致未保存 | 低 | 接受此风险——用户看到的回复已经展示在屏幕上，立即关闭标签页意味着不需要保存 |
| 表命名与现有 `resume_profiles` 不一致 | 低 | 已明确使用 snake_case 无前缀命名（`conversations`/`messages`），与 `resume_profiles` 一致 |

---

## 6. 验收标准

### 功能
- [ ] 用户打开聊天页面，自动创建首个空会话（或加载最近会话）
- [ ] 用户发送消息后，AI 流式回复完成时自动保存到数据库
- [ ] 用户刷新页面后，之前的聊天记录完整恢复
- [ ] 用户可以创建新会话（空聊天区）
- [ ] 用户可以在多个会话之间切换
- [ ] 用户可以删除会话（自动级联删除消息）
- [ ] 首次使用时，如果 localStorage 有历史消息，自动迁移到数据库

### 持久化正确性
- [ ] 消息的 role、content、sources、sortOrder 与界面显示一致
- [ ] source 中的 ref_index 与 AI 回复中的 [n] 标记对应
- [ ] 会话的 messageCount 与实际消息数一致
- [ ] 会话标题自动从首条用户消息截取前 30 字
- [ ] 删除会话后，关联消息在数据库中不存在

### 向后兼容
- [ ] 左侧 UploadPanel + PipelinePanel 功能不变
- [ ] 流式聊天体验不变（逐字展示 + 管线步骤动画）
- [ ] 引用弹窗（CitationModal）功能不变
- [ ] 失败重试不产生重复消息对

### 异常处理
- [ ] 保存消息失败时，界面不报错（静默失败，下次保存覆盖）
- [ ] 网络断开时，聊天功能仍可用（消息在内存中）
- [ ] 会话 API 返回错误时，界面展示错误提示
- [ ] 删除不存在的会话时，API 返回 404 错误

---

## 7. 附录：handleRetry bug 修复详情

**问题**：`handleRetry`（ChatPage.tsx 第 193-245 行）在重试时调用 `setMessages((prev) => [...prev, ...])` 追加新的 user+assistant 消息对，但没有移除之前失败的 user+assistant 消息对。重试一次后，messages 数组包含 `[..., 失败-user, 失败-partial-assistant, 重试-user, 重试-assistant]`。引入数据库持久化后，这个垃圾数组会被保存到 DB 并永久保留。

**修复**：在追加新消息对之前，检查并移除最后一对 user+assistant 消息：

```typescript
setMessages((prev) => {
  const cleaned = [...prev];
  const len = cleaned.length;
  // 移除最后一次失败的 user+assistant 消息对
  if (len >= 2
      && cleaned[len - 2].role === 'user'
      && cleaned[len - 1].role === 'assistant') {
    cleaned.splice(len - 2, 2);
  }
  return [...cleaned, { role: 'user', content: query }, { role: 'assistant', content: '' }];
});
```

该修复属于 M9 范围内——修复一个引入持久化后会放大的既有 bug。
