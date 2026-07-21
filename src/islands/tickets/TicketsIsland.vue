<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import type {
  AgentBackend,
  CheckRun,
  CommitPlan,
  Conversation,
  PrDraft,
  ProposedSubtask,
  RepoCandidate,
  RepoRef,
  SubtaskStatus,
  Ticket,
  TicketDetail,
  TicketStatus,
} from "./types";
import type { Island } from "../../core/types";
import { openUrl } from "@tauri-apps/plugin-opener";
import { useTickets, ApiError } from "./api";
import NButton from "../../ui/NButton.vue";
import NBadge from "../../ui/NBadge.vue";
import NCard from "../../ui/NCard.vue";
import LinkedText from "../../ui/LinkedText.vue";

const props = defineProps<{ island: Island }>();
const api = useTickets(props.island);

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

// --- dispatch backends (where the agents run) --------------------------------
// Probed live by the orchestrator; one-time CLI logins on the machine make
// them available. The chosen backend applies to both dispatch buttons.
const backends = ref<AgentBackend[]>([]);
const backend = ref("claude");

async function loadBackends() {
  try {
    backends.value = await api.listBackends();
    const current = backends.value.find((b) => b.name === backend.value);
    if (!current?.available) {
      backend.value = backends.value.find((b) => b.available)?.name ?? backend.value;
    }
  } catch {
    // Older orchestrator without /backends — keep the default silently.
  }
}
const backendHint = computed(
  () => backends.value.find((b) => b.name === backend.value)?.detail ?? null
);
const noBackendAvailable = computed(
  () => backends.value.length > 0 && backends.value.every((b) => !b.available)
);

// --- live updates -------------------------------------------------------------
// Agent runs mutate state in the background; while a ticket is open, poll the
// detail + conversation (Jira-refresh skipped) so statuses/badges/replies move
// without the user clicking away and back.
const POLL_MS = 2500;
let pollTimer: number | undefined;
async function refreshQuiet() {
  if (!detail.value) return;
  const id = detail.value.ticket.id;
  try {
    const [d, c] = await Promise.all([
      api.getTicket(id, false),
      api.getConversation(id),
    ]);
    if (selectedId.value !== id) return; // user moved on mid-flight
    detail.value = d;
    conversation.value = c;
    const idx = tickets.value.findIndex((t) => t.id === id);
    if (idx >= 0) tickets.value[idx] = d.ticket;
  } catch {
    // transient poll failure — the next tick retries
  }
}

// --- agent conversation -------------------------------------------------------
const conversation = ref<Conversation | null>(null);
const replyText = ref("");
const replying = ref(false);
const instructions = ref("");
const savingInstructions = ref(false);
const instructionsSaved = ref(false);

const convoSubtask = computed(() => conversation.value?.subtask ?? null);
const canReply = computed(
  () =>
    !!convoSubtask.value?.sdk_session_id &&
    (convoSubtask.value.status === "awaiting_input" ||
      convoSubtask.value.status === "done")
);

async function saveInstructions() {
  if (!detail.value) return;
  savingInstructions.value = true;
  instructionsSaved.value = false;
  try {
    const t = await api.updateInstructions(
      detail.value.ticket.id,
      instructions.value || null
    );
    detail.value.ticket = t;
    instructionsSaved.value = true;
    window.setTimeout(() => (instructionsSaved.value = false), 2000);
  } catch (e) {
    processError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    savingInstructions.value = false;
  }
}

async function sendReply() {
  if (!detail.value || !replyText.value) return;
  replying.value = true;
  processError.value = null;
  const text = replyText.value;
  try {
    detail.value = await api.replyToAgent(detail.value.ticket.id, text);
    // Show the reply immediately; the poll takes over from here.
    conversation.value?.messages.push({
      role: "user",
      text,
      at: new Date().toISOString(),
    });
    if (conversation.value?.subtask) conversation.value.subtask.status = "running";
    replyText.value = "";
  } catch (e) {
    processError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    replying.value = false;
  }
}

// --- new (local) ticket -----------------------------------------------------
const showNew = ref(false);
const repos = ref<RepoRef[]>([]);
const newTitle = ref("");
const newRepoId = ref("");
const newDescription = ref("");
const newInstructions = ref("");
const creating = ref(false);
const newError = ref<string | null>(null);

// --- binding a repo checkout -------------------------------------------------
// Repos are auto-created from tickets; when the checkout can't be guessed by
// name, the user picks it once from the git repos found under their repos dir.
const repoCandidates = ref<RepoCandidate[]>([]);
const selectedCheckout = ref("");
const bindingCheckout = ref(false);

async function loadRepoCandidates() {
  try {
    repoCandidates.value = await api.listRepoCandidates();
    if (!selectedCheckout.value && repoCandidates.value.length) {
      selectedCheckout.value = repoCandidates.value[0].path;
    }
  } catch {
    // best-effort — the picker just shows empty
  }
}

async function bindCheckout() {
  const repoId = detail.value?.ticket.repo_id;
  if (!repoId || !selectedCheckout.value) return;
  bindingCheckout.value = true;
  processError.value = null;
  try {
    await api.setRepoCheckout(repoId, selectedCheckout.value);
    await refreshDetail();
  } catch (e) {
    processError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    bindingCheckout.value = false;
  }
}

async function openNew() {
  showNew.value = true;
  newError.value = null;
  if (!repos.value.length) {
    try {
      repos.value = await api.listRepos();
      if (!newRepoId.value && repos.value.length) newRepoId.value = repos.value[0].id;
    } catch (e) {
      newError.value = e instanceof ApiError ? e.message : String(e);
    }
  }
}

function resetNew() {
  showNew.value = false;
  newTitle.value = "";
  newDescription.value = "";
  newInstructions.value = "";
  newError.value = null;
}

async function createLocal() {
  if (!newTitle.value || !newRepoId.value) return;
  creating.value = true;
  newError.value = null;
  try {
    const t = await api.createLocalTicket({
      title: newTitle.value,
      repo_id: newRepoId.value,
      description: newDescription.value || null,
      processing_instructions: newInstructions.value || null,
    });
    tickets.value = [t, ...tickets.value];
    resetNew();
    await select(t);
  } catch (e) {
    newError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    creating.value = false;
  }
}

// --- status filter ----------------------------------------------------------
// Filters on the Jira workflow status (e.g. "Approved", "Dev Done"); local
// tickets fall back to their internal status. Choices persist; finished
// statuses start hidden. A ticket awaiting your reply is never hidden.
const HIDDEN_KEY = "ordinem.tickets.hiddenStatuses";

function statusLabelOf(t: Ticket): string {
  return t.jira?.status ?? t.status.replace(/_/g, " ");
}
function isDoneish(t: Ticket): boolean {
  if (t.jira?.status_category) return t.jira.status_category.toLowerCase() === "done";
  return t.status === "done" || t.status === "pushed" || t.status === "abandoned";
}

const hiddenStatuses = ref<Set<string>>(new Set());
let filterPrefsLoaded = false;

function persistFilterPrefs() {
  try {
    localStorage.setItem(HIDDEN_KEY, JSON.stringify([...hiddenStatuses.value]));
  } catch {
    /* storage unavailable — filter is session-only */
  }
}
function loadFilterPrefs() {
  try {
    const raw = localStorage.getItem(HIDDEN_KEY);
    if (raw) {
      hiddenStatuses.value = new Set(JSON.parse(raw));
      filterPrefsLoaded = true;
    }
  } catch {
    /* ignore */
  }
}
/** First ever run: hide the finished statuses by default. */
function seedDefaultHidden() {
  if (filterPrefsLoaded) return;
  const done = new Set<string>();
  for (const t of tickets.value) if (isDoneish(t)) done.add(statusLabelOf(t));
  hiddenStatuses.value = done;
  filterPrefsLoaded = true;
  persistFilterPrefs();
}

const statusFacets = computed(() => {
  const counts = new Map<string, number>();
  for (const t of tickets.value) {
    const label = statusLabelOf(t);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, count]) => ({ label, count, hidden: hiddenStatuses.value.has(label) }));
});
const hiddenCount = computed(() => statusFacets.value.filter((f) => f.hidden).length);

function toggleStatus(label: string) {
  const next = new Set(hiddenStatuses.value);
  next.has(label) ? next.delete(label) : next.add(label);
  hiddenStatuses.value = next;
  persistFilterPrefs();
}
function showAllStatuses() {
  hiddenStatuses.value = new Set();
  persistFilterPrefs();
}

const visibleTickets = computed(() =>
  tickets.value.filter(
    (t) => t.awaiting_input || !hiddenStatuses.value.has(statusLabelOf(t))
  )
);

// --- grouping (collapsible accordion, closed by default) --------------------
function projectKeyOf(t: Ticket): string {
  return t.jira_project_key ?? (t.source === "local" ? "Local" : "—");
}
const groups = computed(() => {
  const byProject = new Map<string, Ticket[]>();
  for (const t of visibleTickets.value) {
    const key = projectKeyOf(t);
    (byProject.get(key) ?? byProject.set(key, []).get(key)!).push(t);
  }
  return [...byProject.entries()].sort(([a], [b]) => a.localeCompare(b));
});

// Which project groups are expanded. Empty = all collapsed (the default), so
// you open only the one you want.
const openProjects = ref<Set<string>>(new Set());
const isProjectOpen = (key: string) => openProjects.value.has(key);
function toggleProject(key: string) {
  const next = new Set(openProjects.value);
  next.has(key) ? next.delete(key) : next.add(key);
  openProjects.value = next;
}
function openProject(key: string) {
  if (!openProjects.value.has(key)) {
    openProjects.value = new Set(openProjects.value).add(key);
  }
}
/** A collapsed group flashes if any ticket inside is waiting on you. */
const groupNeedsYou = (items: Ticket[]) => items.some((t) => t.awaiting_input);

// --- status/priority display -----------------------------------------------
function statusTone(s: TicketStatus): "accent" | "success" | "muted" {
  if (s === "in_progress" || s === "review") return "accent";
  if (s === "done" || s === "pushed" || s === "ready_to_push") return "success";
  return "muted";
}
const statusPulses = (s: TicketStatus) => s === "in_progress";
/** Accent doubles as "wants your attention" here, as in the review island's
 *  high-severity findings — the palette has no danger tone by design. */
function subtaskTone(s: SubtaskStatus): "accent" | "success" | "muted" {
  if (s === "done") return "success";
  if (s === "running" || s === "failed" || s === "awaiting_input") return "accent";
  return "muted";
}
const subtaskPulses = (s: SubtaskStatus) => s === "running" || s === "awaiting_input";
const subtaskLabel = (s: SubtaskStatus) => (s === "awaiting_input" ? "awaiting you" : s);
function priorityOf(t: Ticket): string | null {
  return t.jira?.priority ?? null;
}
const jira = computed(() => detail.value?.ticket.jira ?? null);
function fmtDate(s: string | null): string {
  if (!s) return "";
  const d = new Date(s);
  return isNaN(d.getTime()) ? s : d.toLocaleString();
}
const isImage = (mime: string | null) => !!mime && mime.startsWith("image/");
function open(url: string | null) {
  if (url) openUrl(url).catch(() => {});
}
/** Browse URL for a sibling issue key, derived from the main issue's url. */
function issueUrl(key: string | null): string | null {
  if (!key || !jira.value?.url) return null;
  return jira.value.url.replace(/\/browse\/.*$/, `/browse/${key}`);
}

// --- data loading -----------------------------------------------------------
async function load() {
  loading.value = true;
  error.value = null;
  try {
    tickets.value = await api.listTickets();
    seedDefaultHidden();
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
    seedDefaultHidden();
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
  openProject(projectKeyOf(t));
  detail.value = null;
  conversation.value = null;
  detailError.value = null;
  processError.value = null;
  detailLoading.value = true;
  branchName.value = t.branch_name ?? suggestBranch(t);
  confirmDocker.value = false;
  replyText.value = "";
  resetShip();
  resetPlan();
  try {
    detail.value = await api.getTicket(t.id);
    instructions.value = detail.value.ticket.processing_instructions ?? "";
    loadProposedIntoEditor();
    conversation.value = await api.getConversation(t.id);
  } catch (e) {
    detailError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    detailLoading.value = false;
  }
}

// --- plan -> gate -> dispatch ----------------------------------------------
// `plan` is the editable copy of the proposal. Nothing here reaches an agent
// until approvePlan() sends it, which is the whole point of the gate.
const plan = ref<ProposedSubtask[]>([]);
const planning = ref(false);
const approving = ref(false);
const dispatching = ref(false);
const planError = ref<string | null>(null);

/** Mini-tickets that already passed the gate — these are (or were) running. */
const dispatched = computed(
  () => detail.value?.subtasks.filter((s) => s.status !== "proposed") ?? []
);
const hasApproved = computed(() =>
  (detail.value?.subtasks ?? []).some((s) => s.status === "pending")
);
const planNeedsDocker = computed(() => plan.value.some((m) => m.needs_docker));

function resetPlan() {
  plan.value = [];
  planError.value = null;
}

/** A proposal survives a reload, so re-open it for editing rather than losing it. */
function loadProposedIntoEditor() {
  const proposed = detail.value?.subtasks.filter((s) => s.status === "proposed") ?? [];
  plan.value = proposed.map((s) => ({
    title: s.title,
    description: s.description ?? "",
    needs_docker: s.needs_docker,
  }));
}

async function proposePlan() {
  if (!detail.value) return;
  planning.value = true;
  planError.value = null;
  try {
    const proposed = await api.planTicket(detail.value.ticket.id);
    plan.value = proposed.map((s) => ({
      title: s.title,
      description: s.description ?? "",
      needs_docker: s.needs_docker,
    }));
    await refreshDetail();
  } catch (e) {
    planError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    planning.value = false;
  }
}

function addMiniTicket() {
  plan.value.push({ title: "", description: "", needs_docker: false });
}

function removeMiniTicket(i: number) {
  plan.value.splice(i, 1);
}

async function approvePlan() {
  if (!detail.value) return;
  approving.value = true;
  planError.value = null;
  try {
    await api.approvePlan(detail.value.ticket.id, plan.value);
    plan.value = [];
    await refreshDetail();
  } catch (e) {
    planError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    approving.value = false;
  }
}

async function dispatchPlan() {
  if (!detail.value) return;
  dispatching.value = true;
  planError.value = null;
  try {
    detail.value = await api.dispatchPlan(
      detail.value.ticket.id,
      branchName.value,
      confirmDocker.value,
      backend.value
    );
    const idx = tickets.value.findIndex((t) => t.id === detail.value!.ticket.id);
    if (idx >= 0) tickets.value[idx] = detail.value.ticket;
  } catch (e) {
    planError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    dispatching.value = false;
  }
}

function suggestBranch(t: Ticket): string {
  const slug = t.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 32);
  const prefix = t.jira_key ? `${t.jira_key.toLowerCase()}-` : "";
  return `feat/${prefix}${slug}`;
}

async function process() {
  if (!detail.value) return;
  processing.value = true;
  processError.value = null;
  try {
    detail.value = await api.processTicket(
      detail.value.ticket.id,
      branchName.value,
      confirmDocker.value,
      backend.value
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

// --- review & ship ----------------------------------------------------------
const shipError = ref<string | null>(null);
const check = ref<CheckRun | null>(null);
const checking = ref(false);
const commitPlan = ref<CommitPlan | null>(null);
const commitMessage = ref("");
const committing = ref(false);
const prDraft = ref<PrDraft | null>(null);
const drafting = ref(false);
const prUrl = ref("");

// Show the ship section once the ticket has left the initial planning phase.
const SHIP_STATUSES = new Set<TicketStatus>([
  "review",
  "checks_failed",
  "ready_to_push",
  "pushed",
  "done",
]);
const canShip = computed(
  () => !!detail.value && SHIP_STATUSES.has(detail.value.ticket.status)
);

function resetShip() {
  shipError.value = null;
  check.value = null;
  commitPlan.value = null;
  commitMessage.value = "";
  prDraft.value = null;
  prUrl.value = "";
}

async function refreshDetail() {
  if (!detail.value) return;
  detail.value = await api.getTicket(detail.value.ticket.id);
  const idx = tickets.value.findIndex((t) => t.id === detail.value!.ticket.id);
  if (idx >= 0) tickets.value[idx] = detail.value.ticket;
}

async function runChecks() {
  if (!detail.value) return;
  checking.value = true;
  shipError.value = null;
  try {
    check.value = await api.runChecks(detail.value.ticket.id);
    await refreshDetail();
  } catch (e) {
    shipError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    checking.value = false;
  }
}

async function draftCommit() {
  if (!detail.value) return;
  shipError.value = null;
  try {
    commitPlan.value = await api.draftCommitPlan(detail.value.ticket.id);
    commitMessage.value = commitPlan.value.proposed_message;
  } catch (e) {
    shipError.value = e instanceof ApiError ? e.message : String(e);
  }
}

async function approveCommit() {
  if (!commitPlan.value) return;
  committing.value = true;
  shipError.value = null;
  try {
    commitPlan.value = await api.approveCommitPlan(
      commitPlan.value.id,
      commitMessage.value
    );
  } catch (e) {
    shipError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    committing.value = false;
  }
}

async function generatePr() {
  if (!detail.value) return;
  drafting.value = true;
  shipError.value = null;
  try {
    prDraft.value = await api.generatePrDraft(detail.value.ticket.id);
  } catch (e) {
    shipError.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    drafting.value = false;
  }
}

async function markOpened() {
  if (!detail.value || !prUrl.value) return;
  shipError.value = null;
  try {
    prDraft.value = await api.markPrOpened(detail.value.ticket.id, prUrl.value);
  } catch (e) {
    shipError.value = e instanceof ApiError ? e.message : String(e);
  }
}

onMounted(() => {
  loadFilterPrefs();
  load();
  loadBackends();
  loadRepoCandidates();
  pollTimer = window.setInterval(() => {
    if (detail.value && !detailLoading.value) refreshQuiet();
  }, POLL_MS);
});
onUnmounted(() => window.clearInterval(pollTimer));
</script>

<template>
  <div class="tickets-island">
    <!-- LIST COLUMN -->
    <div class="list-col">
      <div class="list-head">
        <h2>Tickets</h2>
        <span class="count">
          {{ visibleTickets.length }}<template v-if="visibleTickets.length !== tickets.length">/{{ tickets.length }}</template>
        </span>
        <div class="spacer" />
        <NButton size="sm" @click="openNew">New ticket</NButton>
        <NButton size="sm" variant="primary" :disabled="syncing" @click="sync">
          {{ syncing ? "Syncing…" : "Sync from Jira" }}
        </NButton>
      </div>

      <!-- STATUS FILTER -->
      <details v-if="statusFacets.length > 1" class="filter">
        <summary>
          Status filter<span v-if="hiddenCount" class="filter-note">· {{ hiddenCount }} hidden</span>
        </summary>
        <div class="facets">
          <button
            v-for="f in statusFacets"
            :key="f.label"
            class="facet"
            :class="{ off: f.hidden }"
            :title="f.hidden ? 'Hidden — click to show' : 'Shown — click to hide'"
            @click="toggleStatus(f.label)"
          >
            {{ f.label }} <span class="facet-n">{{ f.count }}</span>
          </button>
          <button v-if="hiddenCount" class="facet clear" @click="showAllStatuses">
            show all
          </button>
        </div>
      </details>

      <!-- NEW LOCAL TICKET -->
      <NCard v-if="showNew" class="new-form">
        <label>
          <span>Title</span>
          <input v-model="newTitle" placeholder="Add live agent progress to the ticket view" />
        </label>
        <label>
          <span>Repo</span>
          <select v-model="newRepoId">
            <option v-for="r in repos" :key="r.id" :value="r.id">{{ r.name }}</option>
          </select>
        </label>
        <label>
          <span>Description</span>
          <textarea v-model="newDescription" rows="3" placeholder="What needs doing, and why." />
        </label>
        <label>
          <span>Processing instructions</span>
          <textarea
            v-model="newInstructions"
            rows="2"
            placeholder="How the agents should approach it."
          />
        </label>
        <p v-if="!repos.length" class="muted">
          No registered repos — add one before creating a local ticket.
        </p>
        <p v-if="newError" class="err">{{ newError }}</p>
        <div class="form-actions">
          <NButton size="sm" @click="resetNew">Cancel</NButton>
          <NButton
            size="sm"
            variant="primary"
            :disabled="creating || !newTitle || !newRepoId"
            @click="createLocal"
          >
            {{ creating ? "Creating…" : "Create" }}
          </NButton>
        </div>
      </NCard>

      <p v-if="syncNote" class="note">{{ syncNote }}</p>
      <p v-if="error" class="err">{{ error }}</p>
      <p v-if="loading" class="muted">Loading…</p>
      <p v-else-if="!tickets.length && !error" class="muted">
        No tickets yet — hit “New ticket”, or “Sync from Jira” for work tickets.
      </p>
      <p v-else-if="!visibleTickets.length && !error" class="muted">
        All {{ tickets.length }} tickets are hidden by the status filter.
        <a class="lnk" @click.prevent="showAllStatuses">Show all</a>
      </p>

      <div v-for="[project, items] in groups" :key="project" class="group">
        <button
          class="group-head"
          :class="{ open: isProjectOpen(project) }"
          @click="toggleProject(project)"
        >
          <span class="chevron">▸</span>
          <span class="group-name">{{ project }}</span>
          <span v-if="groupNeedsYou(items)" class="group-dot" title="A ticket here is waiting on you" />
          <span class="spacer" />
          <span class="group-count">{{ items.length }}</span>
        </button>
        <div v-show="isProjectOpen(project)" class="group-body">
          <button
            v-for="t in items"
            :key="t.id"
            class="ticket-card"
            :class="{ active: t.id === selectedId, unactionable: !t.actionable }"
            @click="select(t)"
          >
            <div class="row1">
              <span class="key">{{ t.jira_key ?? "LOCAL" }}</span>
              <NBadge v-if="t.awaiting_input" tone="accent" pulse>needs you</NBadge>
              <NBadge v-else :tone="statusTone(t.status)" :pulse="statusPulses(t.status)">
                {{ t.status }}
              </NBadge>
            </div>
            <div class="title">{{ t.title }}</div>
            <div class="row2">
              <NBadge v-if="priorityOf(t)">{{ priorityOf(t) }}</NBadge>
              <span v-if="!t.actionable" class="lock" title="No checkout bound — open it to pick one">
                no checkout
              </span>
            </div>
          </button>
        </div>
      </div>
    </div>

    <!-- DETAIL COLUMN -->
    <div class="detail-col">
      <p v-if="!selectedId" class="muted center">Select a ticket to see details.</p>
      <p v-else-if="detailLoading" class="muted">Loading ticket…</p>
      <p v-else-if="detailError" class="err">{{ detailError }}</p>

      <template v-else-if="detail">
        <div class="detail-head">
          <span class="key">{{ detail.ticket.jira_key ?? "LOCAL" }}</span>
          <NBadge :tone="statusTone(detail.ticket.status)" :pulse="statusPulses(detail.ticket.status)">
            {{ detail.ticket.status }}
          </NBadge>
          <NBadge v-if="detail.ticket.awaiting_input" tone="accent" pulse>
            agent awaiting your reply
          </NBadge>
          <NBadge v-if="jira?.status" tone="muted">{{ jira.status }}</NBadge>
          <NBadge v-if="jira?.issue_type">{{ jira.issue_type }}</NBadge>
          <NBadge v-if="priorityOf(detail.ticket)">{{ priorityOf(detail.ticket) }}</NBadge>
        </div>
        <h3 class="detail-title">{{ detail.ticket.title }}</h3>

        <!-- META -->
        <div class="meta" v-if="jira">
          <div v-if="jira.assignee"><span class="mlabel">Assignee</span>{{ jira.assignee }}</div>
          <div v-if="jira.reporter"><span class="mlabel">Reporter</span>{{ jira.reporter }}</div>
          <div v-if="jira.parent"><span class="mlabel">Parent</span>{{ jira.parent.key }} · {{ jira.parent.summary }}</div>
          <div v-if="jira.components.length"><span class="mlabel">Components</span>{{ jira.components.join(", ") }}</div>
          <div v-if="jira.fix_versions.length"><span class="mlabel">Fix versions</span>{{ jira.fix_versions.join(", ") }}</div>
          <div v-if="jira.due_date"><span class="mlabel">Due</span>{{ fmtDate(jira.due_date) }}</div>
          <div v-if="jira.updated"><span class="mlabel">Updated</span>{{ fmtDate(jira.updated) }}</div>
        </div>
        <div class="chips" v-if="jira?.labels.length">
          <span v-for="l in jira.labels" :key="l" class="chip">{{ l }}</span>
        </div>

        <div class="section">
          <div class="label">Description</div>
          <div class="desc">
            <LinkedText :text="jira?.description || detail.ticket.description || '(no description)'" />
          </div>
        </div>

        <div class="section" v-if="jira?.acceptance_criteria">
          <div class="label">Acceptance criteria</div>
          <div class="desc"><LinkedText :text="jira.acceptance_criteria" /></div>
        </div>

        <!-- Jira sub-issues + linked issues -->
        <div class="section" v-if="jira?.subtasks.length">
          <div class="label">Jira sub-issues</div>
          <div v-for="st in jira.subtasks" :key="st.key ?? ''" class="linkrow">
            <a class="key lnk" @click.prevent="open(issueUrl(st.key))">{{ st.key }}</a>
            <span class="ltext">{{ st.summary }}</span>
            <NBadge v-if="st.status" tone="muted">{{ st.status }}</NBadge>
          </div>
        </div>
        <div class="section" v-if="jira?.links.length">
          <div class="label">Linked issues</div>
          <div v-for="(lk, i) in jira.links" :key="i" class="linkrow">
            <span class="rel">{{ lk.relation }}</span>
            <a class="key lnk" @click.prevent="open(issueUrl(lk.key))">{{ lk.key }}</a>
            <span class="ltext">{{ lk.summary }}</span>
          </div>
        </div>

        <!-- Comments -->
        <div class="section" v-if="jira?.comments.length">
          <div class="label">Comments · {{ jira.comments.length }}</div>
          <div v-for="(c, i) in jira.comments" :key="i" class="comment">
            <div class="chead">
              <b>{{ c.author || "—" }}</b><span class="cdate">{{ fmtDate(c.created) }}</span>
            </div>
            <div class="cbody"><LinkedText :text="c.body" /></div>
          </div>
        </div>

        <!-- Attachments -->
        <div class="section" v-if="jira?.attachments.length">
          <div class="label">Attachments</div>
          <div v-for="(a, i) in jira.attachments" :key="i" class="attachment">
            <img
              v-if="isImage(a.mime)"
              class="att-img"
              :src="api.attachmentUrl(detail.ticket.id, i)"
              :alt="a.filename ?? ''"
              loading="lazy"
              @click="open(api.attachmentUrl(detail.ticket.id, i))"
            />
            <div v-else class="linkrow">
              <a class="ltext lnk" @click.prevent="open(api.attachmentUrl(detail.ticket.id, i))">
                {{ a.filename }}
              </a>
              <span class="rel">{{ a.mime }}</span>
            </div>
          </div>
        </div>

        <!-- AGENT — the primary flow: give context, launch one agent, talk to it -->
        <div class="section agent" v-if="detail.ticket.actionable">
          <div class="label">Agent</div>
          <label class="field">
            <span>Your context / instructions</span>
            <textarea
              v-model="instructions"
              rows="4"
              class="input textarea"
              placeholder="What you know that the ticket doesn't say: constraints, where to start, what to avoid…"
            />
          </label>
          <div class="ship-row">
            <NButton size="sm" :disabled="savingInstructions" @click="saveInstructions">
              {{ savingInstructions ? "Saving…" : "Save context" }}
            </NButton>
            <span v-if="instructionsSaved" class="note">saved</span>
          </div>

          <!-- the conversation with the agent -->
          <template v-if="convoSubtask">
            <div class="convo">
              <div
                v-for="(m, i) in conversation?.messages ?? []"
                :key="i"
                class="msg"
                :class="m.role"
              >
                <span class="who">{{ m.role === "user" ? "you" : "agent" }}</span>
                <pre class="bubble">{{ m.text }}</pre>
              </div>
              <p v-if="!(conversation?.messages ?? []).length" class="muted small">
                Agent is working — its reply lands here.
              </p>
            </div>
            <div class="ship-row">
              <NBadge
                :tone="subtaskTone(convoSubtask.status)"
                :pulse="subtaskPulses(convoSubtask.status)"
              >
                {{ subtaskLabel(convoSubtask.status) }}
              </NBadge>
              <span v-if="convoSubtask.error" class="err small">{{ convoSubtask.error }}</span>
            </div>
            <template v-if="canReply">
              <textarea
                v-model="replyText"
                rows="3"
                class="input textarea"
                placeholder="Reply to the agent — it resumes with full context…"
              />
              <div class="ship-row">
                <NButton
                  variant="primary"
                  size="sm"
                  :disabled="replying || !replyText"
                  @click="sendReply"
                >
                  {{ replying ? "Sending…" : "Send reply" }}
                </NButton>
              </div>
            </template>
          </template>

          <!-- launch -->
          <label class="field">
            <span>Branch</span>
            <input v-model="branchName" class="input" />
          </label>
          <label class="check">
            <input type="checkbox" v-model="confirmDocker" />
            Confirm this repo's compose project is the active OrbStack project
          </label>
          <div class="dispatch-row">
            <select v-model="backend" class="input backend-select" title="Where the agent runs">
              <option
                v-for="b in backends"
                :key="b.name"
                :value="b.name"
                :disabled="!b.available"
              >
                {{ b.label }}{{ b.available ? "" : " — unavailable" }}
              </option>
              <option v-if="!backends.length" value="claude">Claude Code</option>
            </select>
            <NButton
              variant="primary"
              :disabled="processing || !branchName || noBackendAvailable"
              @click="process"
            >
              {{
                processing
                  ? "Launching…"
                  : convoSubtask
                    ? "Launch fresh session"
                    : "Launch agent"
              }}
            </NButton>
          </div>
          <p v-if="backendHint" class="muted small">{{ backendHint }}</p>
          <p v-if="noBackendAvailable" class="muted small">
            No agent backend available on this machine — log in to Claude Code
            (`claude`) or Cursor (`cursor-agent login`), or start the local proxy.
          </p>
          <p v-if="processError" class="err">{{ processError }}</p>
        </div>
        <!-- repo auto-linked, but no checkout resolved yet — pick it once -->
        <div class="section" v-else-if="detail.ticket.repo_id">
          <div class="label">Bind a checkout</div>
          <p class="muted small">
            Auto-linked to project <b>{{ detail.ticket.jira_project_key }}</b>, but
            its local checkout wasn't found by name. Pick it once — agents run
            there and worktrees branch off it.
          </p>
          <div class="dispatch-row" v-if="repoCandidates.length">
            <select v-model="selectedCheckout" class="input backend-select">
              <option v-for="c in repoCandidates" :key="c.path" :value="c.path">
                {{ c.name }}
              </option>
            </select>
            <NButton
              variant="primary"
              :disabled="bindingCheckout || !selectedCheckout"
              @click="bindCheckout"
            >
              {{ bindingCheckout ? "Binding…" : "Bind checkout" }}
            </NButton>
          </div>
          <p v-else class="muted small">
            No git checkouts found under your repos folder. Clone the repo there
            (or set REPOS_BASE_DIR in the orchestrator), then reopen this ticket.
          </p>
          <p v-if="processError" class="err">{{ processError }}</p>
        </div>
        <div class="section" v-else>
          <p class="muted">This ticket has no linked repo.</p>
        </div>

        <!-- PLAN (optional mini-tickets, folded away) -->
        <details class="section" v-if="detail.ticket.actionable">
          <summary class="label">Plan mini-tickets (optional)</summary>
          <div class="plan">
          <p class="muted small">
            An agent proposes mini-tickets; you decide what actually runs. They
            share the ticket's worktree and run one at a time, in order.
          </p>

          <NButton size="sm" :disabled="planning" @click="proposePlan">
            {{ planning ? "Planning…" : plan.length ? "Re-plan" : "Propose mini-tickets" }}
          </NButton>

          <!-- the editable proposal: nothing here has run yet -->
          <div v-for="(m, i) in plan" :key="i" class="mini">
            <div class="mini-head">
              <span class="mini-n">{{ i + 1 }}</span>
              <input v-model="m.title" class="input" placeholder="Mini-ticket title" />
              <button class="drop" title="Drop this mini-ticket" @click="removeMiniTicket(i)">
                ×
              </button>
            </div>
            <textarea
              v-model="m.description"
              class="input"
              rows="3"
              placeholder="Everything the agent needs — it won't see the ticket."
            />
            <label class="check">
              <input type="checkbox" v-model="m.needs_docker" />
              Needs docker (runs alone, against the active OrbStack project)
            </label>
          </div>

          <div class="plan-actions" v-if="plan.length || planning === false">
            <NButton size="sm" @click="addMiniTicket">Add mini-ticket</NButton>
            <NButton
              v-if="plan.length"
              size="sm"
              variant="primary"
              :disabled="approving || plan.some((m) => !m.title)"
              @click="approvePlan"
            >
              {{ approving ? "Approving…" : `Approve ${plan.length}` }}
            </NButton>
          </div>
          <p v-if="planNeedsDocker" class="muted small">
            This plan has docker work — confirm the OrbStack project below before dispatching.
          </p>

          <!-- approved, waiting to be set off -->
          <template v-if="hasApproved">
            <div class="approved-note">
              Approved and ready. Dispatch runs the mini-tickets in order, one
              agent at a time, in a worktree on the branch below — your checkout
              is never touched.
            </div>
            <label class="field">
              <span>Branch</span>
              <input v-model="branchName" class="input" />
            </label>
            <label class="check">
              <input type="checkbox" v-model="confirmDocker" />
              Confirm this repo's compose project is the active OrbStack project
            </label>
            <div class="dispatch-row">
              <select v-model="backend" class="input backend-select" title="Where the agents run">
                <option
                  v-for="b in backends"
                  :key="b.name"
                  :value="b.name"
                  :disabled="!b.available"
                >
                  {{ b.label }}{{ b.available ? "" : " — unavailable" }}
                </option>
                <option v-if="!backends.length" value="claude">Claude Code</option>
              </select>
              <NButton
                variant="primary"
                :disabled="dispatching || !branchName || noBackendAvailable"
                @click="dispatchPlan"
              >
                {{ dispatching ? "Dispatching…" : "Dispatch agents" }}
              </NButton>
            </div>
            <p v-if="backendHint" class="muted small">{{ backendHint }}</p>
          </template>
          <p v-if="planError" class="err">{{ planError }}</p>
          </div>
        </details>

        <!-- Agent subtasks (ours, not Jira's) — only what passed the gate -->
        <div class="section" v-if="dispatched.length">
          <div class="label">Agent subtasks</div>
          <p class="muted small" v-if="detail.ticket.branch_name && dispatched.some((s) => s.worktree_path)">
            Working on branch <b>{{ detail.ticket.branch_name }}</b> in
            <code>{{ dispatched.find((s) => s.worktree_path)?.worktree_path }}</code>
          </p>
          <div v-for="s in dispatched" :key="s.id" class="subtask-block">
            <div class="subtask">
              <NBadge :tone="subtaskTone(s.status)" :pulse="subtaskPulses(s.status)">
                {{ subtaskLabel(s.status) }}
              </NBadge>
              <span>{{ s.title }}</span>
              <NBadge v-if="s.needs_docker">docker</NBadge>
              <NBadge v-if="s.backend" tone="muted">{{ s.backend }}</NBadge>
            </div>
            <details v-if="s.result || s.error" class="report">
              <summary>{{ s.error ? "error" : "agent report" }}</summary>
              <pre class="well small">{{ s.error ?? s.result }}</pre>
            </details>
          </div>
        </div>

        <!-- REVIEW & SHIP (post-agent) -->
        <div class="section ship" v-if="canShip">
          <div class="label">Review &amp; ship</div>
          <p class="muted small">
            Read each agent report above, then open branch
            <b>{{ detail.ticket.branch_name || "(no branch)" }}</b> in your editor
            to review the diff. To send agents back in, propose and approve a new
            plan above and dispatch again.
          </p>

          <!-- checks -->
          <div class="ship-row">
            <NButton size="sm" :disabled="checking" @click="runChecks">
              {{ checking ? "Running…" : "Run checks" }}
            </NButton>
            <NBadge
              v-if="check"
              :tone="check.status === 'pass' ? 'success' : 'accent'"
            >{{ check.check_name }} · {{ check.status }}</NBadge>
          </div>
          <pre v-if="check?.output" class="well small">{{ check.output }}</pre>

          <!-- commit plan -->
          <div class="ship-row">
            <NButton size="sm" @click="draftCommit">Draft commit</NButton>
            <NBadge v-if="commitPlan" tone="muted">{{ commitPlan.status }}</NBadge>
          </div>
          <template v-if="commitPlan">
            <textarea
              v-model="commitMessage"
              class="input textarea"
              rows="3"
              placeholder="Commit message…"
            />
            <NButton
              variant="primary"
              size="sm"
              :disabled="committing || !commitMessage"
              @click="approveCommit"
            >{{ committing ? "Committing…" : "Approve & commit" }}</NButton>
          </template>

          <!-- PR draft -->
          <div class="ship-row">
            <NButton size="sm" :disabled="drafting" @click="generatePr">
              {{ drafting ? "Drafting…" : "Generate PR draft" }}
            </NButton>
            <NBadge v-if="prDraft" :tone="prDraft.status === 'opened' ? 'success' : 'muted'">
              {{ prDraft.status }}
            </NBadge>
          </div>
          <template v-if="prDraft">
            <div v-for="(v, k) in (prDraft.template_fields.sections ?? {})" :key="k" class="pr-field">
              <span class="mlabel">{{ k }}</span>
              <span class="ltext">{{ v || "—" }}</span>
            </div>
            <div class="ship-row" v-if="prDraft.status !== 'opened'">
              <input v-model="prUrl" class="input" placeholder="Paste opened PR URL…" />
              <NButton size="sm" :disabled="!prUrl" @click="markOpened">Mark opened</NButton>
            </div>
            <a v-else class="lnk" @click.prevent="open(prDraft.pr_url)">{{ prDraft.pr_url }}</a>
          </template>

          <p v-if="shipError" class="err">{{ shipError }}</p>
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

.filter {
  font-family: var(--font-mono);
}
.filter > summary {
  cursor: pointer;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-dim);
  padding: 2px;
}
.filter > summary:hover {
  color: var(--text);
}
.filter-note {
  color: var(--accent);
  margin-left: 4px;
}
.facets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--sp-2);
}
.facet {
  border: none;
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 4px 9px;
  border-radius: var(--r-pill);
  background: var(--surface);
  box-shadow: var(--shadow-out);
  color: var(--text);
  transition: opacity 120ms ease, box-shadow 120ms ease;
}
.facet.off {
  box-shadow: var(--shadow-in);
  opacity: 0.5;
  text-decoration: line-through;
  color: var(--text-dim);
}
.facet-n {
  color: var(--text-dim);
}
.facet.clear {
  color: var(--accent);
}

.group {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.group-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  border: none;
  cursor: pointer;
  background: var(--surface);
  box-shadow: var(--shadow-out);
  border-radius: var(--r-md);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-dim);
  padding: 8px 12px;
  margin-top: var(--sp-2);
  transition: box-shadow 140ms ease;
}
.group-head:hover {
  color: var(--text);
}
.group-head.open {
  box-shadow: var(--shadow-in);
  color: var(--text);
}
.chevron {
  display: inline-block;
  transition: transform 140ms ease;
  font-size: 9px;
}
.group-head.open .chevron {
  transform: rotate(90deg);
}
.group-name {
  flex: none;
}
.group-count {
  flex: none;
  font-size: 10px;
  color: var(--text-dim);
}
.group-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: group-pulse 1.6s ease-in-out infinite;
}
@keyframes group-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
.group-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
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
  flex-wrap: wrap;
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

.meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px var(--sp-4);
  margin-top: var(--sp-3);
  font-size: 12.5px;
}
.meta > div {
  display: flex;
  gap: 6px;
}
.mlabel {
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-dim);
  min-width: 74px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--sp-3);
}
.chip {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 3px 9px;
  border-radius: var(--r-pill);
  background: var(--surface);
  box-shadow: var(--shadow-out);
  color: var(--text-dim);
}
.linkrow {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: 12.5px;
}
.linkrow .ltext {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rel {
  font-family: var(--font-mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-dim);
}
.lnk {
  cursor: pointer;
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.attachment {
  margin-bottom: var(--sp-2);
}
.att-img {
  max-width: 100%;
  max-height: 320px;
  border-radius: var(--r-md);
  box-shadow: var(--shadow-out);
  cursor: zoom-in;
  display: block;
}
.comment {
  background: var(--surface);
  box-shadow: var(--shadow-in);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.chead {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 12px;
}
.cdate {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-dim);
}
.cbody {
  margin: 0;
  font-family: var(--font-body);
  font-size: 12.5px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.process {
  padding-top: var(--sp-4);
}
.ship {
  padding-top: var(--sp-4);
}
.ship-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.ship-row .input {
  flex: 1;
  min-width: 140px;
}
.textarea {
  height: auto;
  padding: 10px 14px;
  resize: vertical;
  line-height: 1.4;
}
.well {
  margin: 0;
  background: var(--surface);
  box-shadow: var(--shadow-in);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  font-family: var(--font-mono);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: auto;
}
.well.small {
  max-height: 18vh;
  font-size: 11px;
}
.pr-field {
  display: flex;
  gap: 8px;
  font-size: 12.5px;
}
.pr-field .ltext {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.new-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.new-form label {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.new-form label > span {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.new-form input,
.new-form select,
.new-form textarea {
  width: 100%;
  padding: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: var(--surface);
  box-shadow: var(--shadow-in);
  color: var(--text);
  font: inherit;
  font-size: var(--text-sm);
  resize: vertical;
}
.new-form input:focus,
.new-form select:focus,
.new-form textarea:focus {
  outline: 1px solid var(--accent);
}
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

.plan {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  align-items: flex-start;
}
.small {
  font-size: var(--text-xs);
}
.mini {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-out);
}
.mini-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.mini-n {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-dim);
  flex: none;
}
.mini textarea.input {
  resize: vertical;
}
.drop {
  flex: none;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 50%;
  background: var(--surface);
  box-shadow: var(--shadow-out);
  color: var(--text-dim);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.drop:active {
  box-shadow: var(--shadow-in);
}
.plan-actions {
  display: flex;
  gap: var(--space-2);
}
.dispatch-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.backend-select {
  min-width: 200px;
}
.subtask-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.agent {
  gap: var(--sp-3);
}
.agent .field,
.agent .textarea {
  width: 100%;
}
.convo {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  max-height: 45vh;
  overflow: auto;
  padding: var(--sp-2) 0;
}
.msg {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 92%;
}
.msg.user {
  align-self: flex-end;
  align-items: flex-end;
}
.msg .who {
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.msg .bubble {
  margin: 0;
  background: var(--surface);
  box-shadow: var(--shadow-in);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  font-family: var(--font-body);
  font-size: 12.5px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg.user .bubble {
  box-shadow: var(--shadow-out);
}
details.section > summary.label {
  cursor: pointer;
  list-style: revert;
}
.report summary {
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.report .well {
  margin-top: 4px;
  max-height: 40vh;
}
.approved-note {
  font-size: var(--text-xs);
  color: var(--text-dim);
}
</style>
