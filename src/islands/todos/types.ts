// Todos island — a normalized active Todoist task.

export interface TodoTask {
  id: string;
  content: string;
  project_id: string;
  project_name: string;
  due: string | null;
  priority: 1 | 2 | 3 | 4;
  url: string;
}
