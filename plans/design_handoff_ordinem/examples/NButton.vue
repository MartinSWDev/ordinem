<!--
  Ordinem — reference Vue SFC (NButton).
  This is the CANONICAL pattern for the kit: tokens from CSS vars, two elevation
  tools, orange reserved for the primary variant. Copy its conventions for every
  other component (NCard, NToggle, NInput, NTabs, NBadge, NSlider, NSidebarItem…).
-->
<script setup lang="ts">
defineProps<{
  variant?: 'primary' | 'secondary'
  size?: 'sm' | 'md'
  disabled?: boolean
}>()
defineEmits<{ (e: 'click', ev: MouseEvent): void }>()
</script>

<template>
  <button
    class="n-btn"
    :class="[`v-${variant ?? 'secondary'}`, `s-${size ?? 'md'}`]"
    :disabled="disabled"
    @click="$emit('click', $event)"
  >
    <slot />
  </button>
</template>

<style scoped>
.n-btn {
  border: none;
  cursor: pointer;
  font-family: var(--font-body);
  font-weight: 600;
  color: var(--text);
  background: var(--surface);          /* equals parent — required for neumorphism */
  border-radius: var(--r-md);
  box-shadow: var(--shadow-out);        /* raised */
  transition: box-shadow 160ms ease, transform 160ms ease, filter 160ms ease;
}
.n-btn:hover:not(:disabled) { transform: translateY(-1px); }
.n-btn:active:not(:disabled) { box-shadow: var(--shadow-in); transform: none; }  /* pressed = inset */
.n-btn:focus-visible { outline: none; box-shadow: var(--shadow-out), 0 0 0 1.5px var(--accent); }
.n-btn:disabled { opacity: .5; cursor: not-allowed; }

/* variants */
.v-primary { background: var(--accent); color: #fff; }
.v-primary:active:not(:disabled) { filter: brightness(.94); box-shadow: var(--shadow-in); }

/* sizes */
.s-md { height: 38px; padding: 0 18px; font-size: 13px; }
.s-sm { height: 30px; padding: 0 14px; font-size: 12px; }
</style>
