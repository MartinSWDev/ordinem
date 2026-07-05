<script setup lang="ts">
defineProps<{
  label: string;
  active?: boolean;
}>();
defineEmits<{ (e: "click"): void }>();
</script>

<template>
  <button
    class="n-sidebar-item"
    :class="{ active }"
    :title="label"
    :aria-label="label"
    :aria-current="active ? 'page' : undefined"
    @click="$emit('click')"
  >
    <slot />
  </button>
</template>

<style scoped>
.n-sidebar-item {
  width: 44px;
  height: 44px;
  border: none;
  border-radius: 14px;
  background: var(--surface);
  box-shadow: var(--shadow-out);
  color: var(--text-dim);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-mono);
  font-size: 13px;
  cursor: pointer;
  transition: box-shadow 160ms ease, transform 160ms ease, color 160ms ease;
}
.n-sidebar-item:hover { transform: translateY(-1px); }
.n-sidebar-item:focus-visible { outline: none; box-shadow: var(--shadow-out), 0 0 0 1.5px var(--accent); }
.n-sidebar-item.active {
  box-shadow: var(--shadow-in);
  color: var(--accent);
  transform: none;
}
</style>
