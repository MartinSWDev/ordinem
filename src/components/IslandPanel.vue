<script setup lang="ts">
import { ref, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { Island, FetchOutcome } from "../types";

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
  <section>
    <h2>{{ island.title }}</h2>
    <p>{{ island.endpoint_base }}</p>

    <p v-if="loading">Loading...</p>

    <template v-else-if="result?.status === 'ok'">
      <pre>{{ result.body }}</pre>
    </template>

    <div v-else-if="result?.status === 'error'">
      <p>Failed to load this island: {{ result.message }}</p>
      <button @click="load">Retry</button>
    </div>

    <button v-if="!loading" @click="load">Refresh</button>
  </section>
</template>
