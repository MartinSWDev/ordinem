<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { Manifest } from "./types";
import NSidebarItem from "./components/NSidebarItem.vue";
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
  <main class="shell">
    <nav class="sidebar">
      <div class="brand" title="Ordinem">ō</div>

      <div class="sidebar-divider" />

      <NSidebarItem
        v-for="island in manifest?.islands ?? []"
        :key="island.id"
        :label="island.title"
        :active="island.id === selectedIslandId"
        @click="selectedIslandId = island.id"
      >
        {{ island.title.charAt(0).toUpperCase() }}
      </NSidebarItem>

      <div class="sidebar-spacer" />

      <NSidebarItem label="Reload config" @click="loadManifest">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 4v6h6" />
          <path d="M20 20v-6h-6" />
          <path d="M4.5 15a8 8 0 0 0 14.5 3M19.5 9A8 8 0 0 0 5 6" />
        </svg>
      </NSidebarItem>
    </nav>

    <div class="content">
      <div class="topbar">
        <div class="device-name">{{ manifest?.device_name ?? "—" }}</div>
      </div>

      <p v-if="manifestError" class="manifest-error">
        Could not load manifest: {{ manifestError }}
      </p>

      <IslandPanel v-else-if="selectedIsland" :island="selectedIsland" :key="selectedIsland.id" />

      <p v-else class="empty-state">No islands configured in the manifest.</p>
    </div>
  </main>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  background: var(--surface);
  color: var(--text);
}

.sidebar {
  width: 70px;
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 20px 0;
  border-right: 1px solid rgba(0, 0, 0, 0.04);
}

.brand {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: var(--accent);
  box-shadow: var(--shadow-out);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 18px;
}

.sidebar-divider {
  width: 24px;
  height: 1px;
  background: rgba(0, 0, 0, 0.07);
  margin: 2px 0;
}

.sidebar-spacer {
  flex: 1;
}

.content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-6);
  overflow: auto;
}

.topbar {
  display: flex;
  align-items: center;
}

.device-name {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--text-dim);
}

.manifest-error,
.empty-state {
  font-size: 13.5px;
  color: var(--text-dim);
}
</style>
