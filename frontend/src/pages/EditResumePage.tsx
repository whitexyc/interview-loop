import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  Typography,
  Space,
  Flex,
  Spin,
  Alert,
} from 'antd';
import {
  PlusOutlined,
  DeleteOutlined,
  SaveOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons';
import PasswordGuard from '../components/PasswordGuard';
import { getResume, updateResume } from '../services/resumeService';
import type { ResumeDTO } from '../types/resume';

const { Title, Text } = Typography;
const { TextArea } = Input;

export default function EditResumePage() {
  const navigate = useNavigate();
  const [resume, setResume] = useState<ResumeDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [form] = Form.useForm<ResumeDTO>();

  const fetchResume = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getResume();
      setResume(data);
      form.setFieldsValue(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [form]);

  useEffect(() => {
    fetchResume();
  }, [fetchResume]);

  const handleSave = useCallback(async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      setError(null);
      setSuccess(false);
      await updateResume(values);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      }
    } finally {
      setSaving(false);
    }
  }, [form]);

  // ─── Loading / Error ───
  if (loading) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 80 }}>
        <Spin size="large" />
        <div style={{ marginTop: 16, color: '#475569' }}>加载简历数据...</div>
      </div>
    );
  }

  if (error && !resume) {
    return (
      <Alert
        type="error"
        message="加载失败"
        description={error}
        showIcon
        style={{ marginTop: 32, borderRadius: 8 }}
      />
    );
  }

  // ─── Edit Form ───
  return (
    <PasswordGuard authKey="resume_edit_auth" title="验证身份" description="请输入密码以编辑简历">
    <Form
      form={form}
      layout="vertical"
      size="large"
      onFinish={handleSave}
      style={{ maxWidth: 800, margin: '0 auto' }}
    >
      <Space direction="vertical" size={24} style={{ width: '100%' }}>
        {/* Header */}
        <Flex justify="space-between" align="center" wrap="wrap" gap={12}>
          <div>
            <Title level={4} style={{ margin: 0, color: '#0f172a' }}>
              编辑简历
            </Title>
            <Text type="secondary">修改完成后点击保存</Text>
          </div>
          <Space>
            <Button
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate('/')}
              shape="round"
            >
              返回
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              htmlType="submit"
              loading={saving}
              shape="round"
              style={{ height: 40 }}
            >
              保存
            </Button>
          </Space>
        </Flex>

        {success && (
          <Alert type="success" message="简历已保存" showIcon closable onClose={() => setSuccess(false)} style={{ borderRadius: 8 }} />
        )}

        {error && (
          <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} style={{ borderRadius: 8 }} />
        )}

        {/* 个人信息 */}
        <Card
          className="resume-card"
          styles={{ body: { padding: 24 } }}
          style={{
            borderRadius: 16,
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            border: '1px solid rgba(226,232,240,0.6)',
          }}
        >
          <Title level={5} style={{ margin: 0, marginBottom: 20, color: '#0f172a' }}>
            个人信息
          </Title>
          <Flex wrap gap="16px">
            <Form.Item label="姓名" name="name" rules={[{ required: true }]} style={{ flex: '1 1 200px' }}>
              <Input variant="filled" style={{ borderRadius: 8 }} />
            </Form.Item>
            <Form.Item label="性别" name="gender" style={{ flex: '1 1 120px' }}>
              <Select variant="filled" style={{ borderRadius: 8 }}>
                <Select.Option value="男">男</Select.Option>
                <Select.Option value="女">女</Select.Option>
              </Select>
            </Form.Item>
          </Flex>
          <Flex wrap gap="16px">
            <Form.Item label="电话" name="phone" style={{ flex: '1 1 200px' }}>
              <Input variant="filled" style={{ borderRadius: 8 }} />
            </Form.Item>
            <Form.Item label="邮箱" name="email" rules={[{ type: 'email', message: '请输入有效邮箱' }]} style={{ flex: '1 1 250px' }}>
              <Input variant="filled" style={{ borderRadius: 8 }} />
            </Form.Item>
          </Flex>
          <Form.Item label="求职意向" name="jobIntent">
            <Input variant="filled" style={{ borderRadius: 8 }} />
          </Form.Item>
          <Form.Item label="GitHub" name="github">
            <Input variant="filled" style={{ borderRadius: 8 }} />
          </Form.Item>
        </Card>

        {/* 教育背景 */}
        <Card
          className="resume-card"
          styles={{ body: { padding: 24 } }}
          style={{
            borderRadius: 16,
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            border: '1px solid rgba(226,232,240,0.6)',
          }}
        >
          <Title level={5} style={{ margin: 0, marginBottom: 16, color: '#0f172a' }}>
            教育背景
          </Title>
          <Form.List name="education">
            {(fields, { add, remove }) => (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                {fields.map(({ key, name, ...rest }) => (
                  <div
                    key={key}
                    style={{
                      padding: 16,
                      borderRadius: 12,
                      border: '1px solid #e2e8f0',
                      background: '#fafafa',
                      position: 'relative',
                    }}
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => remove(name)}
                      style={{ position: 'absolute', top: 8, right: 8 }}
                    />
                    <Flex wrap gap="12px">
                      <Form.Item {...rest} label="学校" name={[name, 'school']} rules={[{ required: true }]} style={{ flex: '1 1 250px' }}>
                        <Input variant="filled" style={{ borderRadius: 8 }} />
                      </Form.Item>
                      <Form.Item {...rest} label="专业" name={[name, 'major']} style={{ flex: '1 1 200px' }}>
                        <Input variant="filled" style={{ borderRadius: 8 }} />
                      </Form.Item>
                    </Flex>
                    <Flex wrap gap="12px">
                      <Form.Item {...rest} label="届别" name={[name, 'gradeYear']} style={{ flex: '1 1 150px' }}>
                        <Input variant="filled" style={{ borderRadius: 8 }} />
                      </Form.Item>
                      <Form.Item {...rest} label="排名" name={[name, 'rank']} style={{ flex: '1 1 200px' }}>
                        <Input variant="filled" style={{ borderRadius: 8 }} />
                      </Form.Item>
                    </Flex>
                    <Form.Item {...rest} label="核心课程（逗号分隔）" name={[name, 'courses']} getValueFromEvent={(e) => e.target.value.split(',').map((s: string) => s.trim())} getValueProps={(v) => ({ value: Array.isArray(v) ? v.join(', ') : '' })}>
                      <Input variant="filled" style={{ borderRadius: 8 }} placeholder="数据结构, 操作系统, 计算机网络" />
                    </Form.Item>
                  </div>
                ))}
                <Button type="dashed" onClick={() => add({ school: '', major: '', gradeYear: '', rank: '', courses: [] })} icon={<PlusOutlined />} block style={{ borderRadius: 8, height: 44 }}>
                  添加教育经历
                </Button>
              </Space>
            )}
          </Form.List>
        </Card>

        {/* 荣誉证书 */}
        <Card
          className="resume-card"
          styles={{ body: { padding: 24 } }}
          style={{
            borderRadius: 16,
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            border: '1px solid rgba(226,232,240,0.6)',
          }}
        >
          <Title level={5} style={{ margin: 0, marginBottom: 16, color: '#0f172a' }}>
            荣誉证书
          </Title>
          <Form.List name="honors">
            {(fields, { add, remove }) => (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {fields.map(({ key, name, ...rest }) => (
                  <Flex key={key} gap={8} align="baseline">
                    <Form.Item {...rest} name={[name]} rules={[{ required: true }]} style={{ flex: 1, marginBottom: 0 }}>
                      <Input variant="filled" placeholder="输入荣誉名称" style={{ borderRadius: 8 }} />
                    </Form.Item>
                    <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />
                  </Flex>
                ))}
                <Button type="dashed" onClick={() => add('')} icon={<PlusOutlined />} block style={{ borderRadius: 8, height: 44 }}>
                  添加荣誉
                </Button>
              </Space>
            )}
          </Form.List>
        </Card>

        {/* 专业技能 */}
        <Card
          className="resume-card"
          styles={{ body: { padding: 24 } }}
          style={{
            borderRadius: 16,
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            border: '1px solid rgba(226,232,240,0.6)',
          }}
        >
          <Title level={5} style={{ margin: 0, marginBottom: 16, color: '#0f172a' }}>
            专业技能
          </Title>
          <Form.List name="skills">
            {(fields, { add, remove }) => (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                {fields.map(({ key, name, ...rest }) => (
                  <div
                    key={key}
                    style={{
                      padding: 16,
                      borderRadius: 12,
                      border: '1px solid #e2e8f0',
                      background: '#fafafa',
                      position: 'relative',
                    }}
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => remove(name)}
                      style={{ position: 'absolute', top: 8, right: 8 }}
                    />
                    <Form.Item {...rest} label="分类名称" name={[name, 'category']} rules={[{ required: true }]} style={{ marginBottom: 12 }}>
                      <Input variant="filled" style={{ borderRadius: 8 }} placeholder="如：Java 核心技术" />
                    </Form.Item>
                    <Form.Item {...rest} label="技能项（逗号分隔）" name={[name, 'items']} getValueFromEvent={(e) => e.target.value.split(',').map((s: string) => s.trim())} getValueProps={(v) => ({ value: Array.isArray(v) ? v.join(', ') : '' })}>
                      <Input variant="filled" style={{ borderRadius: 8 }} placeholder="集合框架, 高并发 JUC, JVM 调优" />
                    </Form.Item>
                  </div>
                ))}
                <Button type="dashed" onClick={() => add({ category: '', items: [] })} icon={<PlusOutlined />} block style={{ borderRadius: 8, height: 44 }}>
                  添加技能分类
                </Button>
              </Space>
            )}
          </Form.List>
        </Card>

        {/* 项目经历 */}
        <Card
          className="resume-card"
          styles={{ body: { padding: 24 } }}
          style={{
            borderRadius: 16,
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            border: '1px solid rgba(226,232,240,0.6)',
          }}
        >
          <Title level={5} style={{ margin: 0, marginBottom: 16, color: '#0f172a' }}>
            项目经历
          </Title>
          <Form.List name="projects">
            {(fields, { add, remove }) => (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                {fields.map(({ key, name, ...rest }) => (
                  <div
                    key={key}
                    style={{
                      padding: 16,
                      borderRadius: 12,
                      border: '1px solid #e2e8f0',
                      background: '#fafafa',
                      position: 'relative',
                    }}
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => remove(name)}
                      style={{ position: 'absolute', top: 8, right: 8 }}
                    />
                    <Flex wrap gap="12px">
                      <Form.Item {...rest} label="项目名称" name={[name, 'name']} rules={[{ required: true }]} style={{ flex: '1 1 250px', marginBottom: 12 }}>
                        <Input variant="filled" style={{ borderRadius: 8 }} />
                      </Form.Item>
                      <Form.Item {...rest} label="角色" name={[name, 'role']} style={{ flex: '1 1 150px', marginBottom: 12 }}>
                        <Input variant="filled" style={{ borderRadius: 8 }} />
                      </Form.Item>
                    </Flex>
                    <Form.Item {...rest} label="时间" name={[name, 'time']} style={{ marginBottom: 12 }}>
                      <Input variant="filled" style={{ borderRadius: 8 }} placeholder="2025.10 - 2026.02" />
                    </Form.Item>
                    <Form.Item {...rest} label="描述" name={[name, 'description']} style={{ marginBottom: 12 }}>
                      <TextArea variant="filled" rows={3} style={{ borderRadius: 8 }} />
                    </Form.Item>
                    <Form.Item {...rest} label="关键成果（逗号分隔）" name={[name, 'highlights']} getValueFromEvent={(e) => e.target.value.split(',').map((s: string) => s.trim())} getValueProps={(v) => ({ value: Array.isArray(v) ? v.join(', ') : '' })}>
                      <TextArea variant="filled" rows={3} style={{ borderRadius: 8 }} placeholder="成果1, 成果2, 成果3" />
                    </Form.Item>
                  </div>
                ))}
                <Button type="dashed" onClick={() => add({ name: '', role: '', time: '', description: '', highlights: [] })} icon={<PlusOutlined />} block style={{ borderRadius: 8, height: 44 }}>
                  添加项目
                </Button>
              </Space>
            )}
          </Form.List>
        </Card>

        {/* 自我评价 */}
        <Card
          className="resume-card"
          styles={{ body: { padding: 24 } }}
          style={{
            borderRadius: 16,
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            border: '1px solid rgba(226,232,240,0.6)',
          }}
        >
          <Title level={5} style={{ margin: 0, marginBottom: 16, color: '#0f172a' }}>
            自我评价
          </Title>
          <Form.Item name="selfEvaluation" style={{ marginBottom: 0 }}>
            <TextArea variant="filled" rows={6} style={{ borderRadius: 8 }} />
          </Form.Item>
        </Card>

        {/* Bottom actions */}
        <Flex justify="center" gap={12}>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
            size="large"
            shape="round"
            style={{ height: 44, minWidth: 120 }}
          >
            返回
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            htmlType="submit"
            loading={saving}
            size="large"
            shape="round"
            style={{ height: 44, minWidth: 120 }}
          >
            保存
          </Button>
        </Flex>

        <div style={{ height: 40 }} />
      </Space>
    </Form>
    </PasswordGuard>
  );
}
