<script setup lang="ts">
import { ref, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { Island, FetchOutcome } from "../types";
import NCard from "./NCard.vue";
import NButton from "./NButton.vue";

const props = defineProps<{ island: Island }>();

const loading = ref(false);
const result = ref<FetchOutcome | null>(null);

async function load() {
  loading.value = true;
  result.value = null;
  result.value = await invoke<FetchOutcome>("fetch_island", {
    endpointBase: props.island.endpoint_base,
    credentialRef: props.island.credential_ref,
  });
  loading.value = false;
}

watch(() => props.island.id, load, { immediate: true });
</script>

<template>
  <NCard class="island-panel">
    <div class="header">
      <h3>{{ island.title }}</h3>
      <span class="endpoint">{{ island.endpoint_base }}</span>
      <div class="spacer" />
      <NButton size="sm" :disabled="loading" @click="load">Refresh</NButton>
    </div>

    <p v-if="loading" class="status">Loading…</p>

    <pre v-else-if="result?.status === 'ok'" class="well">{{ result.body }}</pre>

    <div v-else-if="result?.status === 'error'" class="error">
      <p>Failed to load this island: {{ result.message }}</p>
      <NButton size="sm" @click="load">Retry</NButton>
    </div>
  </NCard>
</template>

<style scoped>
.island-panel {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.header {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.header h3 {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 16px;
}

.endpoint {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
}

.spacer {
  flex: 1;
}

.status {
  margin: 0;
  font-size: 13px;
  color: var(--text-dim);
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
  max-height: 50vh;
  overflow: auto;
}

.error {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  align-items: flex-start;
}

.error p {
  margin: 0;
  font-size: 13px;
  color: var(--text-dim);
}
</style>
