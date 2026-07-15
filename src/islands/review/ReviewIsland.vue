<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import type { Island } from "../../core/types";
import type { RepoRef, Review, ReviewFinding } from "./types";
import { useReview, ApiError } from "./api";
import NButton from "../../ui/NButton.vue";
import NBadge from "../../ui/NBadge.vue";

const props = defineProps<{ island: Island }>();
const api = useReview(props.island);

const repos = ref<RepoRef[]>([]);
const repoId = ref<string>("");
const baseBranch = ref("");
const headBranch = ref("");

const running = ref(false);
const error = ref<string | null>(null);
const review = ref<Review | null>(null);

const selectedRepo = computed(() => repos.value.find((r) => r.id === repoId.value) ?? null);
const canRun = computed(() => !!selectedRepo.value?.local_path && !running.value);

const SEVERITIES = ["high", "medium", "low"] as const;
type Severity = (typeof SEVERITIES)[number];

const grouped = computed(() => {
  const by: Record<Severity, ReviewFinding[]> = { high: [], medium: [], low: [] };
  for (const f of review.value?.result.findings ?? []) {
    (by[f.severity] ?? by.low).push(f);
  }
  return SEVERITIES.map((sev) => ({ sev, items: by[sev] })).filter((g) => g.items.length);
});
const severityTone = (s: Severity) => (s === "high" ? "accent" : "muted");

async function loadRepos() {
  error.value = null;
  try {
    repos.value = await api.listRepos();
    if (!repoId.value && repos.value.length) {
      repoId.value = (repos.value.find((r) => r.local_path) ?? repos.value[0]).id;
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e);
  }
}

async function run() {
  if (!selectedRepo.value) return;
  running.value = true;
  error.value = null;
  review.value = null;
  try {
    review.value = await api.runReview(
      selectedRepo.value.id,
      baseBranch.value,
      headBranch.value
    );
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    running.value = false;
  }
}

onMounted(loadRepos);
</script>

<template>
  <div class="review-island">
    <!-- CONTROLS -->
    <div class="controls">
      <div class="head">
        <h2>Pre-PR review</h2>
        <div class="spacer" />
        <NButton variant="primary" :disabled="!canRun" @click="run">
          {{ running ? "Reviewing…" : "Run review" }}
        </NButton>
      </div>

      <div class="fields">
        <label class="field">
          <span>Repo</span>
          <select v-model="repoId" class="input">
            <option v-for="r in repos" :key="r.id" :value="r.id">
              {{ r.name }}{{ r.local_path ? "" : " (no checkout)" }}
            </option>
          </select>
        </label>
        <label class="field">
          <span>Base</span>
          <input v-model="baseBranch" class="input" :placeholder="selectedRepo?.default_branch ?? 'main'" />
        </label>
        <label class="field">
          <span>Head</span>
          <input v-model="headBranch" class="input" placeholder="current branch" />
        </label>
      </div>

      <p v-if="selectedRepo && !selectedRepo.local_path" class="muted">
        <b>{{ selectedRepo.name }}</b> has no local checkout registered — set its
        <code>local_path</code> to review it.
      </p>
      <p v-if="error" class="err">{{ error }}</p>
    </div>

    <!-- RESULTS -->
    <div v-if="running" class="muted center">Reviewing the diff…</div>

    <template v-else-if="review">
      <div class="summary">
        <div class="label">
          Summary · {{ review.base_branch }} → {{ review.head_branch }} ·
          {{ review.result.findings.length }} finding{{ review.result.findings.length === 1 ? "" : "s" }}
        </div>
        <p class="summary-text">{{ review.result.summary }}</p>
      </div>

      <p v-if="!review.result.findings.length" class="muted center">No findings 🎉</p>

      <div v-for="g in grouped" :key="g.sev" class="group">
        <div class="group-head">
          <NBadge :tone="severityTone(g.sev)">{{ g.sev }}</NBadge>
          <span class="count">{{ g.items.length }}</span>
        </div>
        <div v-for="(f, i) in g.items" :key="i" class="finding">
          <div class="frow">
            <span class="file">{{ f.file }}<span v-if="f.line">:{{ f.line }}</span></span>
            <NBadge tone="muted">{{ f.category }}</NBadge>
          </div>
          <p class="comment">{{ f.comment }}</p>
          <pre v-if="f.suggestion" class="suggestion">{{ f.suggestion }}</pre>
        </div>
      </div>
    </template>

    <p v-else class="muted center">Pick a repo and run a review.</p>
  </div>
</template>

<style scoped>
.review-island {
  height: 100%;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.controls {
  background: var(--surface);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-out);
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.head h2 {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 18px;
}
.spacer {
  flex: 1;
}
.fields {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: var(--sp-3);
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
  padding: 0 12px;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text);
  outline: none;
}
.input:focus {
  box-shadow: var(--shadow-in), 0 0 0 1.5px var(--accent);
}

.summary {
  background: var(--surface);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-out);
  padding: var(--sp-4);
}
.summary-text {
  margin: var(--sp-2) 0 0;
  font-size: 13.5px;
  line-height: 1.5;
}
.label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-dim);
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
  margin-top: var(--sp-2);
}
.count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
}
.finding {
  background: var(--surface);
  box-shadow: var(--shadow-out);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.frow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}
.file {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.comment {
  margin: 0;
  font-size: 13px;
  line-height: 1.45;
}
.suggestion {
  margin: 0;
  background: var(--surface);
  box-shadow: var(--shadow-in);
  border-radius: var(--r-sm);
  padding: var(--sp-2) var(--sp-3);
  font-family: var(--font-mono);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
code {
  font-family: var(--font-mono);
  font-size: 12px;
}
.muted {
  color: var(--text-dim);
  font-size: 13px;
}
.center {
  margin: auto;
  text-align: center;
}
.err {
  color: var(--accent);
  font-size: 13px;
  margin: 0;
}
</style>
