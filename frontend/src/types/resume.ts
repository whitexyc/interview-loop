/** 教育经历 */
export interface EducationItem {
  school: string;
  major: string;
  gradeYear: string;
  rank: string;
  courses: string[];
}

/** 技能分类 */
export interface SkillItem {
  category: string;
  items: string[];
}

/** 项目经历 */
export interface ProjectItem {
  name: string;
  role: string;
  time: string;
  description: string;
  highlights: string[];
}

/** 简历完整数据传输对象（对应后端 ResumeDTO） */
export interface ResumeDTO {
  id: number;
  name: string;
  gender: string;
  phone: string;
  email: string;
  jobIntent: string;
  github: string;
  education: EducationItem[];
  honors: string[];
  skills: SkillItem[];
  projects: ProjectItem[];
  selfEvaluation: string;
  updatedAt: string;
}

