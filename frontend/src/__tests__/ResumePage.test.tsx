import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ResumePage from '../pages/ResumePage';
import { getResume } from '../services/resumeService';
import type { ResumeDTO } from '../types/resume';

// Mock the resume service
vi.mock('../services/resumeService', () => ({
  getResume: vi.fn(),
}));

const mockResume: ResumeDTO = {
  id: 1,
  name: '张三',
  gender: '男',
  phone: '13800138000',
  email: 'xiongyicheng@example.com',
  jobIntent: '前端开发工程师',
  github: 'https://github.com/xiongyicheng',
  education: [
    {
      school: '华中科技大学',
      major: '计算机科学与技术',
      gradeYear: '2024届',
      rank: '前10%',
      courses: ['数据结构', '操作系统', '计算机网络'],
    },
  ],
  honors: ['一等奖学金', 'ACM 银牌'],
  skills: [
    {
      category: '前端',
      items: ['React', 'TypeScript'],
    },
  ],
  projects: [
    {
      name: '在线简历系统',
      role: '前端负责人',
      time: '2024.01 - 2024.06',
      description: '一个基于 React 的简历管理平台',
      highlights: ['实现了简历编辑和预览功能', '使用 Ant Design 构建 UI'],
    },
  ],
  selfEvaluation: '热爱编程，学习能力强',
  updatedAt: '2024-06-01T00:00:00Z',
};

describe('ResumePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should set document title on mount', async () => {
    vi.mocked(getResume).mockResolvedValue(mockResume);
    render(<ResumePage />);
    await waitFor(() => {
      expect(document.title).toBe('个人简历 - 张三');
    });
  });

  it('should show loading spinner while fetching', () => {
    // Never resolve the promise to keep loading state
    vi.mocked(getResume).mockImplementation(() => new Promise(() => {}));
    render(<ResumePage />);
    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('should show 404 error message when API returns 404', async () => {
    const error = new Error('Request failed with status code 404');
    (error as any).isAxiosError = true;
    (error as any).response = { status: 404, data: {} };
    (error as any).code = undefined;
    vi.mocked(getResume).mockRejectedValue(error);

    render(<ResumePage />);
    await waitFor(() => {
      expect(screen.getByText('简历加载失败')).toBeInTheDocument();
    });
  });

  it('should show timeout message on request timeout', async () => {
    const error = new Error('timeout of 10000ms exceeded');
    (error as any).isAxiosError = true;
    (error as any).code = 'ECONNABORTED';
    (error as any).response = undefined;
    vi.mocked(getResume).mockRejectedValue(error);

    render(<ResumePage />);
    await waitFor(() => {
      expect(screen.getByText('请求超时，请稍后重试')).toBeInTheDocument();
    });
  });

  it('should show network error message on Network Error', async () => {
    const error = new Error('Network Error');
    (error as any).isAxiosError = true;
    (error as any).code = undefined;
    (error as any).response = undefined;
    vi.mocked(getResume).mockRejectedValue(error);

    render(<ResumePage />);
    await waitFor(() => {
      expect(screen.getByText('网络异常，请检查连接')).toBeInTheDocument();
    });
  });

  it('should show generic error for other errors', async () => {
    const error = new Error('Something went wrong');
    (error as any).isAxiosError = true;
    (error as any).response = { status: 500, data: { msg: '服务器内部错误' } };
    (error as any).code = undefined;
    vi.mocked(getResume).mockRejectedValue(error);

    render(<ResumePage />);
    await waitFor(() => {
      expect(screen.getByText('服务器内部错误')).toBeInTheDocument();
    });
  });

  it('should render resume data correctly', async () => {
    vi.mocked(getResume).mockResolvedValue(mockResume);

    render(<ResumePage />);

    // Wait for loading to finish and data to appear
    await waitFor(() => {
      expect(screen.getByText('张三')).toBeInTheDocument();
    });

    // Check personal info
    expect(screen.getByText('男')).toBeInTheDocument();
    expect(screen.getByText('13800138000')).toBeInTheDocument();
    expect(screen.getByText('xiongyicheng@example.com')).toBeInTheDocument();
    expect(screen.getByText('前端开发工程师')).toBeInTheDocument();

    // Check education
    expect(screen.getByText('华中科技大学')).toBeInTheDocument();
    expect(screen.getByText('计算机科学与技术')).toBeInTheDocument();
    expect(screen.getByText('2024届')).toBeInTheDocument();

    // Check honors
    expect(screen.getByText('一等奖学金')).toBeInTheDocument();
    expect(screen.getByText('ACM 银牌')).toBeInTheDocument();

    // Check skills
    expect(screen.getByText('前端')).toBeInTheDocument();
    expect(screen.getByText('React')).toBeInTheDocument();
    expect(screen.getByText('TypeScript')).toBeInTheDocument();

    // Check projects
    expect(screen.getByText('在线简历系统')).toBeInTheDocument();
    expect(screen.getByText('前端负责人 | 2024.01 - 2024.06')).toBeInTheDocument();

    // Check self evaluation
    expect(screen.getByText('热爱编程，学习能力强')).toBeInTheDocument();
  });

  it('should show retry button on error', async () => {
    const error = new Error('Request failed with status code 404');
    (error as any).isAxiosError = true;
    (error as any).response = { status: 404, data: {} };
    (error as any).code = undefined;
    vi.mocked(getResume).mockRejectedValue(error);

    render(<ResumePage />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument();
    });
  });
});
