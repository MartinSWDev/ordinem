import { islandClient } from "../../core/api";
import type { Island } from "../../core/types";
import type { TodoTask } from "./types";

export { ApiError } from "../../core/api";

/** Todos-island client: the read-only active-task rollup. */
export function useTodos(island: Island) {
  const { request } = islandClient(island);
  return {
    listTodos: () => request<TodoTask[]>("GET", ""),
  };
}
