<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import type { Island, Ticket, TicketDetail, TicketStatus } from "../../types";
import { useOrchestrator, ApiError } from "../../api/orchestrator";
import NButton from "../NButton.vue";
import NBadge from "../NBadge.vue";

const props = defineProps<{ island: Island }>();
const api = useOrchestrator(props.island);

const tickets = ref<Ticket[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
const syncing = ref(false);
const syncNote = ref<string | null>(null);

const selectedId = ref<string | null>(null);
const detail = ref<TicketDetail | null>(null);
const detailLoading = ref(false);
const detailError = ref<string | null>(null);

// process form
const branchName = ref("");
const confirmDocker = ref(false);
const processing = ref(false);
const processError = ref<string | null>(null);

// --- grouping ---------------------------------------------------------------
const groups = computed(() => {
  const byProject = new Map<string, Ticket[]>();
  for (const t of tickets.value) {
    const key = t.jira_project_key ?? "—";
    (byProject.get(key) ?? byProject.set(key, []).get(key)!).push(t);
  }
  return [...byProject.entries()].sort(([a], [b]) => a.localeCompare(b));
});

// --- status/priority display -----------------------------------------------
function statusTone(s: TicketStatus): "accent" | "success" | "muted" {
  if (s === "in_progress" || s === "review") return "accent";
  if (s === "done" || s === "pushed" || s === "ready_to_push") return "success";
  return "muted";
}
const statusPulses = (s: TicketStatus) => s === "in_progress";
function priorityOf(t: Ticket): string | null {
  return t.raw_jira?.fields?.priority?.name ?? null;
}

// --- data loading -----------------------------------------------------------
async function load() {
  loading.value = true;
  error.value = null;
  try {
    tickets.value = await api.listTickets();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function sync() {
  syncing.value = true;
  syncNote.value = null;
  error.value = null;
  try {
    const res = await api.syncMyTickets();
    tickets.value = res.tickets;
    syncNote.value = `Synced ${res.synced} ticket${res.synced === 1 ? "" : "s"}`;
    if (res.unregistered_projects.length) {
      syncNote.value += ` · unregistered: ${res.unregistered_projects.join(", ")}`;
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    syncing.value = false;
  }
}

async function select(t: Ticket) {
  selectedId.value = t.id;
  detail.value = null;
  detailError.value = null;
  processError.value = null;
  detailLoading.value = true;
  branchName.value = t.branch_name ?? suggestBranch(t);
  confirmDocker.value = false;
  try {
    detail.value = await api.getTicket(t.id);
  } catch (e) {
    detailError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    detailLoading.value = false;
  }
}

function suggestBranch(t: Ticket): string {
  const slug = t.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 32);
  return `feat/${t.jira_key.toLowerCase()}-${slug}`;
}

async function process() {
  if (!detail.value) return;
  processing.value = true;
  processError.value = null;
  try {
    detail.value = await api.processTicket(
      detail.value.ticket.id,
      branchName.value,
      confirmDocker.value
    );
    // reflect the new status in the list too
    const idx = tickets.value.findIndex((t) => t.id === detail.value!.ticket.id);
    if (idx >= 0) tickets.value[idx] = detail.value.ticket;
  } catch (e) {
    processError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    processing.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="tickets-island">
    <!-- LIST COLUMN -->
    <div class="list-col">
      <div class="list-head">
        <h2>Tickets</h2>
        <span class="count">{{ tickets.length }}</span>
        <div class="spacer" />
        <NButton size="sm" variant="primary" :disabled="syncing" @click="sync">
          {{ syncing ? "Syncing…" : "Sync from Jira" }}
        </NButton>
      </div>

      <p v-if="syncNote" class="note">{{ syncNote }}</p>
      <p v-if="error" class="err">{{ error }}</p>
      <p v-if="loading" class="muted">Loading…</p>
      <p v-else-if="!tickets.length && !error" class="muted">
        No tickets yet — hit “Sync from Jira”.
      </p>

      <div v-for="[project, items] in groups" :key="project" class="group">
        <div class="group-head">
          <span>{{ project }}</span><span>{{ items.length }}</span>
        </div>
        <button
          v-for="t in items"
          :key="t.id"
          class="ticket-card"
          :class="{ active: t.id === selectedId, unactionable: !t.actionable }"
          @click="select(t)"
        >
          <div class="row1">
            <span class="key">{{ t.jira_key }}</span>
            <NBadge :tone="statusTone(t.status)" :pulse="statusPulses(t.status)">
              {{ t.status }}
            </NBadge>
          </div>
          <div class="title">{{ t.title }}</div>
          <div class="row2">
            <NBadge v-if="priorityOf(t)">{{ priorityOf(t) }}</NBadge>
            <span v-if="!t.actionable" class="lock" title="No registered repo — not actionable">
              no repo
            </span>
          </div>
        </button>
      </div>
    </div>

    <!-- DETAIL COLUMN -->
    <div class="detail-col">
      <p v-if="!selectedId" class="muted center">Select a ticket to see details.</p>
      <p v-else-if="detailLoading" class="muted">Loading ticket…</p>
      <p v-else-if="detailError" class="err">{{ detailError }}</p>

      <template v-else-if="detail">
        <div class="detail-head">
          <span class="key">{{ detail.ticket.jira_key }}</span>
          <NBadge :tone="statusTone(detail.ticket.status)" :pulse="statusPulses(detail.ticket.status)">
            {{ detail.ticket.status }}
          </NBadge>
          <NBadge v-if="priorityOf(detail.ticket)">{{ priorityOf(detail.ticket) }}</NBadge>
        </div>
        <h3 class="detail-title">{{ detail.ticket.title }}</h3>

        <div class="section">
          <div class="label">Description</div>
          <pre class="desc">{{ detail.ticket.description || "(no description)" }}</pre>
        </div>

        <div class="section" v-if="detail.subtasks.length">
          <div class="label">Subtasks</div>
          <div v-for="s in detail.subtasks" :key="s.id" class="subtask">
            <NBadge :tone="s.status === 'done' ? 'success' : s.status === 'running' ? 'accent' : 'muted'"
              :pulse="s.status === 'running'">{{ s.status }}</NBadge>
            <span>{{ s.title }}</span>
          </div>
        </div>

        <!-- PROCESS -->
        <div class="section process">
          <div class="label">Set agents off</div>
          <template v-if="detail.ticket.actionable">
            <label class="field">
              <span>Branch</span>
              <input v-model="branchName" class="input" />
            </label>
            <label class="check">
              <input type="checkbox" v-model="confirmDocker" />
              Confirm this repo's compose project is the active OrbStack project
            </label>
            <NButton variant="primary" :disabled="processing || !branchName" @click="process">
              {{ processing ? "Dispatching…" : "Process ticket" }}
            </NButton>
            <p v-if="processError" class="err">{{ processError }}</p>
          </template>
          <p v-else class="muted">
            This ticket's project has no registered repo, so it can't be dispatched.
            Register a repo for <b>{{ detail.ticket.jira_project_key }}</b> and re-sync.
          </p>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.tickets-island {
  display: grid;
  grid-template-columns: minmax(280px, 380px) 1fr;
  gap: var(--sp-4);
  height: 100%;
  min-height: 0;
}

.list-col,
.detail-col {
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.detail-col {
  background: var(--surface);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-out);
  padding: var(--sp-4);
}

.list-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.list-head h2 {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 18px;
}
.count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
}
.spacer {
  flex: 1;
}

.group {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.group-head {
  display: flex;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-dim);
  padding: 0 2px;
  margin-top: var(--sp-2);
}

.ticket-card {
  text-align: left;
  border: none;
  cursor: pointer;
  background: var(--surface);
  box-shadow: var(--shadow-out);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: box-shadow 160ms ease, transform 160ms ease;
  font-family: var(--font-body);
}
.ticket-card:hover {
  transform: translateY(-1px);
}
.ticket-card.active {
  box-shadow: var(--shadow-in);
}
.ticket-card.unactionable {
  opacity: 0.7;
}
.row1 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}
.row2 {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.key {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
}
.title {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.3;
  color: var(--text);
}
.lock {
  font-family: var(--font-mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-dim);
}

.detail-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.detail-title {
  margin: var(--sp-2) 0 0;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 20px;
  letter-spacing: -0.01em;
}
.section {
  margin-top: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.desc {
  margin: 0;
  font-family: var(--font-body);
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--surface);
  box-shadow: var(--shadow-in);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  max-height: 30vh;
  overflow: auto;
}
.subtask {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: 13px;
}

.process {
  padding-top: var(--sp-4);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field span {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.input {
  height: 40px;
  border: none;
  border-radius: var(--r-md);
  background: var(--surface);
  box-shadow: var(--shadow-in);
  padding: 0 14px;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text);
  outline: none;
}
.input:focus {
  box-shadow: var(--shadow-in), 0 0 0 1.5px var(--accent);
}
.check {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: 12.5px;
  color: var(--text-dim);
}

.muted {
  color: var(--text-dim);
  font-size: 13px;
}
.center {
  margin: auto;
}
.note {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--success);
  margin: 0;
}
.err {
  color: var(--accent);
  font-size: 13px;
  margin: 0;
}
</style>
