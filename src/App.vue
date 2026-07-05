<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { Manifest } from "./types";
import IslandPanel from "./components/IslandPanel.vue";

const manifest = ref<Manifest | null>(null);
const manifestError = ref<string | null>(null);
const selectedIslandId = ref<string | null>(null);

const selectedIsland = computed(() =>
  manifest.value?.islands.find((island) => island.id === selectedIslandId.value) ?? null
);

async function loadManifest() {
  manifestError.value = null;
  try {
    manifest.value = await invoke<Manifest>("load_manifest");
    selectedIslandId.value = manifest.value.islands[0]?.id ?? null;
  } catch (e) {
    manifest.value = null;
    manifestError.value = String(e);
  }
}

onMounted(loadManifest);
</script>

<template>
  <main style="display: flex; height: 100vh">
    <nav style="border-right: 1px solid #ccc; padding: 1em; min-width: 12em">
      <button @click="loadManifest">Reload config</button>

      <p v-if="manifestError">Could not load manifest: {{ manifestError }}</p>

      <ul v-else-if="manifest">
        <li v-for="island in manifest.islands" :key="island.id">
          <button @click="selectedIslandId = island.id">{{ island.title }}</button>
        </li>
      </ul>
    </nav>

    <div style="flex: 1; padding: 1em">
      <IslandPanel v-if="selectedIsland" :island="selectedIsland" :key="selectedIsland.id" />
      <p v-else-if="!manifestError">No island selected.</p>
    </div>
  </main>
</template>
