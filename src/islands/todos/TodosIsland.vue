<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";
import type { Island } from "../../core/types";
import NBadge from "../../ui/NBadge.vue";
import NButton from "../../ui/NButton.vue";
import NCard from "../../ui/NCard.vue";
import { ApiError, useTodos } from "./api";
import type { TodoTask } from "./types";

const props = defineProps<{ island: Island }>();
const api = useTodos(props.island);
const tasks = ref<TodoTask[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

const groups = computed(() => {
  const byProject = new Map<string, TodoTask[]>();
  for (const task of tasks.value) {
    const key = task.project_name || "Unknown project";
    (byProject.get(key) ?? byProject.set(key, []).get(key)!).push(task);
  }
  return [...byProject.entries()].sort(([a], [b]) => a.localeCompare(b));
});

function dueLabel(due: string | null) {
  if (!due) return null;
  const date = new Date(due.length === 10 ? `${due}T00:00:00` : due);
  if (Number.isNaN(date.getTime())) return due;
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    ...(due.length > 10 ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

function priorityLabel(priority: number) {
  return priority === 4 ? "Urgent" : `P${5 - priority}`;
}

function priorityTone(priority: number): "accent" | "muted" {
  return priority >= 3 ? "accent" : "muted";
}

function openTask(task: TodoTask) {
  if (task.url) openUrl(task.url).catch(() => {});
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    tasks.value = await api.listTodos();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="todos-island" aria-labelledby="todos-title">
    <header class="head">
      <div>
        <h2 id="todos-title">Todos</h2>
        <p>{{ tasks.length }} active task{{ tasks.length === 1 ? "" : "s" }}</p>
      </div>
      <NButton size="sm" variant="primary" :disabled="loading" @click="load">
        {{ loading ? "Syncing…" : "Sync" }}
      </NButton>
    </header>

    <div v-if="error" class="error" role="alert">
      <strong>Todos unavailable</strong>
      <span>{{ error }}</span>
      <NButton size="sm" @click="load">Try again</NButton>
    </div>
    <p v-else-if="loading && !tasks.length" class="state">Loading todos…</p>
    <p v-else-if="!tasks.length" class="state">No active Todoist tasks.</p>

    <div v-else class="projects" :aria-busy="loading">
      <NCard v-for="[project, items] in groups" :key="project" class="project">
        <div class="project-head">
          <h3>{{ project }}</h3>
          <span>{{ items.length }} task{{ items.length === 1 ? "" : "s" }}</span>
        </div>
        <div class="task-list">
          <button
            v-for="task in items"
            :key="task.id"
            class="task"
            type="button"
            :title="task.url ? 'Open in Todoist' : undefined"
            @click="openTask(task)"
          >
            <span class="check" aria-hidden="true" />
            <span class="task-copy">
              <span class="content">{{ task.content }}</span>
              <span v-if="task.due" class="due">Due {{ dueLabel(task.due) }}</span>
            </span>
            <NBadge :tone="priorityTone(task.priority)">
              {{ priorityLabel(task.priority) }}
            </NBadge>
          </button>
        </div>
      </NCard>
    </div>
  </section>
</template>

<style scoped>
.todos-island { max-width: 760px; width: 100%; margin: 0 auto; }
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--sp-6); }
h2 { margin: 0; font: 600 24px var(--font-display); }
.head p { margin: 4px 0 0; color: var(--text-dim); font: 10px var(--font-mono); letter-spacing: .12em; text-transform: uppercase; }
.projects { display: flex; flex-direction: column; gap: var(--sp-4); opacity: 1; transition: opacity 160ms ease; }
.projects[aria-busy="true"] { opacity: .6; }
.project { padding: var(--sp-4); }
.project-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--sp-3); }
.project-head h3 { margin: 0; font: 600 15px var(--font-display); }
.project-head > span { color: var(--text-dim); font: 10px var(--font-mono); }
.task-list { display: flex; flex-direction: column; gap: var(--sp-2); }
.task { width: 100%; min-height: 52px; display: grid; grid-template-columns: 18px 1fr auto; align-items: center; gap: var(--sp-3); padding: var(--sp-2) var(--sp-3); border: 0; border-radius: var(--r-md); background: var(--surface); box-shadow: var(--shadow-in); color: var(--text); font: inherit; text-align: left; cursor: pointer; }
.task:hover { transform: translateY(-1px); }
.task:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.check { width: 13px; height: 13px; border-radius: 50%; box-shadow: var(--shadow-out); }
.task-copy { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.content { overflow: hidden; text-overflow: ellipsis; font-size: 13px; font-weight: 500; }
.due { color: var(--text-dim); font: 10px var(--font-mono); }
.state { padding: var(--sp-6); color: var(--text-dim); text-align: center; font-size: 13px; }
.error { display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-2); padding: var(--sp-4); border-radius: var(--r-lg); box-shadow: var(--shadow-in); color: var(--accent); font-size: 13px; }
.error span { color: var(--text-dim); }
@media (max-width: 560px) { .task { grid-template-columns: 16px 1fr; } .task :deep(.n-badge) { grid-column: 2; justify-self: start; } }
</style>
