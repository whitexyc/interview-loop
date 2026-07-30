import { useEffect, useState, useCallback } from 'react';
import {
  Card,
  Tag,
  Typography,
  Spin,
  Alert,
  Button,
  Space,
  Flex,
  Divider,
} from 'antd';
import {
  GithubOutlined,
  PhoneOutlined,
  MailOutlined,
  AimOutlined,
  BookOutlined,
  TrophyOutlined,
  ToolOutlined,
  ProjectOutlined,
  HeartOutlined,
} from '@ant-design/icons';
import { getResume } from '../services/resumeService';
import type { ResumeDTO } from '../types/resume';

const { Title, Text, Paragraph } = Typography;

/* ─── Section Header ─── */
function SectionHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 6,
          background: '#eff6ff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#1e40af',
          fontSize: 15,
        }}
      >
        {icon}
      </div>
      <Title level={5} style={{ margin: 0, color: '#0f172a' }}>
        {title}
      </Title>
    </div>
  );
}

/* ─── Resume Content ─── */
function ResumeContent({ resume }: { resume: ResumeDTO }) {
  return (
    <>
      <style>{`
        .resume-card:hover {
          box-shadow: 0 8px 24px rgba(0,0,0,0.08), 0 2px 6px rgba(0,0,0,0.04) !important;
          transform: translateY(-1px);
        }
      `}</style>
    <Space direction="vertical" size={28} style={{ width: '100%' }}>
      {/* ═══ Profile Header ═══ */}
      <Card
        className="resume-card"
        styles={{ body: { padding: 32 } }}
        style={{
          borderRadius: 16,
          boxShadow: '0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03)',
          border: '1px solid rgba(226,232,240,0.6)',
          transition: 'box-shadow 0.25s ease, transform 0.25s ease',
        }}
      >
        <Flex align="center" gap={24} wrap="wrap">
          {/* Avatar */}
          <div
            style={{
              width: 80,
              height: 80,
              borderRadius: 20,
              background: 'linear-gradient(135deg, #1e40af 0%, #0891b2 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontSize: 32,
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            {resume.name.charAt(0)}
          </div>

          {/* Info */}
          <div style={{ flex: 1, minWidth: 200 }}>
            <Title level={2} style={{ margin: 0, color: '#0f172a' }}>
              {resume.name}
            </Title>
            <Text type="secondary" style={{ fontSize: 16, display: 'block', marginTop: 4, lineHeight: 1.6 }}>
              <AimOutlined style={{ marginRight: 6 }} />
              {resume.jobIntent}
            </Text>
            <Flex wrap gap={6} style={{ marginTop: 12 }}>
              <Tag icon={<PhoneOutlined />} color="default" style={{ borderRadius: 6, padding: '2px 10px' }}>
                {resume.phone}
              </Tag>
              <Tag icon={<MailOutlined />} color="default" style={{ borderRadius: 6, padding: '2px 10px' }}>
                {resume.email}
              </Tag>
              <Tag icon={<GithubOutlined />} color="default" style={{ borderRadius: 6, padding: '2px 10px' }}>
                <a href={resume.github} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>
                  GitHub
                </a>
              </Tag>
              <Tag
                color="default"
                style={{ borderRadius: 6, padding: '2px 10px' }}
              >
                {resume.gender}
              </Tag>
            </Flex>
          </div>
        </Flex>
      </Card>

      {/* ═══ Education ═══ */}
      <Card
        className="resume-card"
        styles={{ body: { padding: 24 } }}
        style={{
          borderRadius: 12,
          boxShadow: '0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03)',
          border: '1px solid rgba(226,232,240,0.6)',
          transition: 'box-shadow 0.25s ease, transform 0.25s ease',
        }}
      >
        <SectionHeader icon={<BookOutlined />} title="教育背景" />
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {resume.education.map((item, idx) => (
            <div key={idx}>
              <Flex justify="space-between" align="baseline" wrap="wrap">
                <Title level={5} style={{ margin: 0 }}>
                  {item.school}
                </Title>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  {item.gradeYear}
                </Text>
              </Flex>
              <Flex wrap gap={4} style={{ marginTop: 6 }}>
                <Text style={{ color: '#475569' }}>{item.major}</Text>
                <Text type="secondary">|</Text>
                <Text style={{ color: '#475569' }}>排名: {item.rank}</Text>
              </Flex>
              <div style={{ marginTop: 8 }}>
                <Text strong style={{ fontSize: 15, color: '#475569' }}>
                  核心课程：
                </Text>
                <Flex wrap gap="4px 6px" style={{ marginTop: 4 }}>
                  {item.courses.map((course) => (
                    <Tag
                      key={course}
                      style={{
                        borderRadius: 4,
                        background: '#f1f5f9',
                        border: 'none',
                        color: '#475569',
                        padding: '0 8px',
                      }}
                    >
                      {course}
                    </Tag>
                  ))}
                </Flex>
              </div>
              {idx < resume.education.length - 1 && (
                <Divider style={{ margin: '8px 0' }} />
              )}
            </div>
          ))}
        </Space>
      </Card>

      {/* ═══ Honors ═══ */}
      <Card
        className="resume-card"
        styles={{ body: { padding: 24 } }}
        style={{
          borderRadius: 12,
          boxShadow: '0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03)',
          border: '1px solid rgba(226,232,240,0.6)',
          transition: 'box-shadow 0.25s ease, transform 0.25s ease',
        }}
      >
        <SectionHeader icon={<TrophyOutlined />} title="荣誉证书" />
        <Flex wrap gap="6px 10px">
          {resume.honors.map((honor) => (
            <Tag
              key={honor}
              style={{
                borderRadius: 6,
                padding: '4px 14px',
                fontSize: 14,
                background: 'linear-gradient(135deg, #fef3c7, #fde68a)',
                border: '1px solid #f59e0b33',
                color: '#92400e',
                fontWeight: 500,
              }}
            >
              <TrophyOutlined style={{ marginRight: 4, color: '#f59e0b' }} />
              {honor}
            </Tag>
          ))}
        </Flex>
      </Card>

      {/* ═══ Skills ═══ */}
      <Card
        className="resume-card"
        styles={{ body: { padding: 24 } }}
        style={{
          borderRadius: 12,
          boxShadow: '0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03)',
          border: '1px solid rgba(226,232,240,0.6)',
          transition: 'box-shadow 0.25s ease, transform 0.25s ease',
        }}
      >
        <SectionHeader icon={<ToolOutlined />} title="专业技能" />
        <Flex wrap gap={12}>
          {resume.skills.map((skill) => (
            <div
              key={skill.category}
              style={{
                flex: '1 1 200px',
                minWidth: 180,
                padding: '16px 20px',
                background: '#f8fafc',
                borderRadius: 10,
                border: '1px solid #e2e8f0',
              }}
            >
              <Text
                strong
                style={{
                  fontSize: 13,
                  color: '#1e40af',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                {skill.category}
              </Text>
              <Flex wrap gap="4px 6px" style={{ marginTop: 10 }}>
                {skill.items.map((item) => (
                  <Tag
                    key={item}
                    style={{
                      borderRadius: 4,
                      background: '#eff6ff',
                      border: '1px solid #bfdbfe',
                      color: '#1e40af',
                      padding: '2px 10px',
                      fontSize: 13,
                    }}
                  >
                    {item}
                  </Tag>
                ))}
              </Flex>
            </div>
          ))}
        </Flex>
      </Card>

      {/* ═══ Projects ═══ */}
      <Card
        className="resume-card"
        styles={{ body: { padding: 24 } }}
        style={{
          borderRadius: 12,
          boxShadow: '0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03)',
          border: '1px solid rgba(226,232,240,0.6)',
          transition: 'box-shadow 0.25s ease, transform 0.25s ease',
        }}
      >
        <SectionHeader icon={<ProjectOutlined />} title="项目经历" />
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {resume.projects.map((project) => (
            <div
              key={project.name}
              style={{
                padding: '20px 24px',
                borderRadius: 12,
                border: '1px solid #e2e8f0',
                borderLeft: '3px solid #1e40af',
                background: '#fff',
                transition: 'box-shadow 0.2s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow =
                  '0 4px 12px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = 'none';
              }}
            >
              <Flex justify="space-between" align="baseline" wrap="wrap" style={{ marginBottom: 8 }}>
                <Title level={5} style={{ margin: 0, color: '#0f172a' }}>
                  {project.name}
                </Title>
                <Text type="secondary" style={{ fontSize: 14 }}>
                  {project.role} | {project.time}
                </Text>
              </Flex>
              <Paragraph
                style={{ color: '#475569', marginBottom: 12, lineHeight: 1.7, fontSize: 16 }}
              >
                {project.description}
              </Paragraph>
              <Text strong style={{ fontSize: 15, color: '#475569' }}>
                关键成果
              </Text>
              <ul style={{ margin: '6px 0 0', paddingLeft: 20, color: '#475569' }}>
                {project.highlights.map((h, i) => (
                  <li key={i} style={{ lineHeight: 1.8, fontSize: 15 }}>
                    {h}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </Space>
      </Card>

      {/* ═══ Self Evaluation ═══ */}
      <Card
        className="resume-card"
        styles={{ body: { padding: 24 } }}
        style={{
          borderRadius: 12,
          boxShadow: '0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03)',
          border: '1px solid rgba(226,232,240,0.6)',
          transition: 'box-shadow 0.25s ease, transform 0.25s ease',
        }}
      >
        <SectionHeader icon={<HeartOutlined />} title="自我评价" />
        <Paragraph
          style={{
            fontSize: 16,
            lineHeight: 1.7,
            color: '#334155',
            whiteSpace: 'pre-wrap',
            margin: 0,
          }}
        >
          {resume.selfEvaluation}
        </Paragraph>
      </Card>
    </Space>
    </>
  );
}

/* ─── Page Component ─── */
export default function ResumePage() {
  const [resume, setResume] = useState<ResumeDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchResume = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getResume();
      setResume(data);
    } catch (err: unknown) {
      const axiosError = err as Record<string, unknown>;
      if (axiosError.isAxiosError) {
        const response = axiosError.response as Record<string, unknown> | undefined;
        const code = axiosError.code as string | undefined;
        if (response && (response as Record<string, unknown>).status === 404) {
          setError('简历加载失败');
        } else if (code === 'ECONNABORTED') {
          setError('请求超时，请稍后重试');
        } else if (!response) {
          setError('网络异常，请检查连接');
        } else {
          const data = response.data as Record<string, unknown> | undefined;
          if (data && typeof data.msg === 'string') {
            setError(data.msg);
          } else {
            setError(err instanceof Error ? err.message : '未知错误');
          }
        }
      } else {
        setError(err instanceof Error ? err.message : '未知错误');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = '个人简历 - 张三';
    fetchResume();
  }, [fetchResume]);

  if (loading) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 120 }}>
        <Spin size="large" />
        <div style={{ marginTop: 16, color: '#475569', fontSize: 16 }}>加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        type="error"
        message="加载失败"
        description={error}
        showIcon
        action={<Button onClick={fetchResume}>重试</Button>}
        style={{ marginTop: 48 }}
      />
    );
  }

  if (resume === null) return null;

  return <ResumeContent resume={resume} />;
}
