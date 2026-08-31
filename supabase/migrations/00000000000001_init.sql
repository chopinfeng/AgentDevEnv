-- 业务主库初始 schema（本地：supabase start；CI：supabase db push）
-- 迁移是改库的唯一方式，禁止在 Studio 手改。

create extension if not exists vector;

-- 终端用户任务记录（业务数据放 Supabase，会话状态放 DO SQLite）
create table if not exists agent_tasks (
  id uuid primary key default gen_random_uuid(),
  session_id text not null,
  input text not null,
  output text,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

-- 人工反馈/评分：进化管线的训练信号
create table if not exists agent_feedback (
  id uuid primary key default gen_random_uuid(),
  task_id uuid references agent_tasks(id),
  rating smallint check (rating between 1 and 5),
  comment text,
  created_at timestamptz not null default now()
);

create index if not exists idx_tasks_session on agent_tasks (session_id, created_at desc);
