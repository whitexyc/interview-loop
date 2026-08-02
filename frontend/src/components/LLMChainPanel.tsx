/**
 * # LLMChainPanel — LLM 供应商顺序设置面板（module-029）
 *
 * ## 组件职责
 * 1. 加载当前降级链顺序（GET /ai/llm/chain）
 * 2. 上移/下移调整供应商优先级
 * 3. 保存到后端（PUT /ai/llm/chain，持久化 Redis + 即时生效）
 *
 * ## 数据流
 * 挂载 → getLLMChain() 显示当前顺序
 *      → 上下移调整本地顺序（dirty 标记）
 *      → 保存 → updateLLMChain() → 后端校验 + 持久化 + 清缓存重建
 */
import { useEffect, useState, useCallback } from 'react';
import { Typography, Flex, Button, message, Spin } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined, SaveOutlined } from '@ant-design/icons';
import { getLLMChain, updateLLMChain } from '../services/ragService';

const { Text } = Typography;

/** 供应商显示名映射（后端返回的是内部 key） */
const PROVIDER_LABELS: Record<string, string> = {
  qwen: '通义千问 (Qwen)',
  zhipu: '智谱 GLM',
  deepseek: 'DeepSeek',
  claude: 'Claude',
  modelscope: 'ModelScope',
};

export default function LLMChainPanel() {
  const [chain, setChain] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  /** 加载当前降级链顺序 */
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setChain(await getLLMChain());
      setDirty(false);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '获取供应商顺序失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  /** 上下移调整本地顺序 */
  const move = (index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= chain.length) return;
    setChain((prev) => {
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setDirty(true);
  };

  /** 保存顺序到后端 */
  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const saved = await updateLLMChain(chain);
      setChain(saved);
      setDirty(false);
      message.success('供应商顺序已保存（即时生效）');
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }, [chain]);

  return (
    <div style={{
      background: '#fff', borderRadius: 12, padding: 16, maxWidth: 420,
      border: '1px solid rgba(226,232,240,0.6)',
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
    }}>
      <Typography.Title level={5} style={{ marginBottom: 4, color: '#0f172a', fontSize: 15 }}>
        LLM 供应商顺序
      </Typography.Title>
      <Text style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginBottom: 10 }}>
        按优先级排列，失败自动切换下一个。顺序持久化到 Redis，保存后即时生效（无需重启）
      </Text>

      {loading ? (
        <Spin size="small" style={{ display: 'block', margin: '8px auto' }} />
      ) : (
        <Flex vertical gap={4}>
          {chain.map((p, i) => (
            <Flex key={p} justify="space-between" align="center" style={{
              padding: '5px 8px', borderRadius: 6, background: '#f8fafc',
              border: '1px solid #e2e8f0',
            }}>
              <Flex gap={8} align="center">
                <span style={{ fontSize: 11, color: '#94a3b8', width: 16, textAlign: 'center' }}>
                  {i + 1}
                </span>
                <Text strong style={{ fontSize: 12, color: '#0f172a' }}>
                  {PROVIDER_LABELS[p] || p}
                </Text>
              </Flex>
              <Flex gap={2}>
                <Button
                  size="small" type="text"
                  icon={<ArrowUpOutlined />}
                  disabled={i === 0}
                  onClick={() => move(i, -1)}
                />
                <Button
                  size="small" type="text"
                  icon={<ArrowDownOutlined />}
                  disabled={i === chain.length - 1}
                  onClick={() => move(i, 1)}
                />
              </Flex>
            </Flex>
          ))}
        </Flex>
      )}

      <Button
        type="primary" size="small" block icon={<SaveOutlined />}
        loading={saving} disabled={!dirty || loading}
        onClick={handleSave}
        style={{ marginTop: 10, borderRadius: 6 }}
      >
        保存顺序
      </Button>
    </div>
  );
}
