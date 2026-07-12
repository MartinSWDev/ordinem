<!--
  Ordinem — canonical button pattern (from design handoff).
  Tokens from CSS vars, two elevation tools, orange reserved for primary.
-->
<script setup lang="ts">
defineProps<{
  variant?: "primary" | "secondary";
  size?: "sm" | "md";
  disabled?: boolean;
}>();
defineEmits<{ (e: "click", ev: MouseEvent): void }>();
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
  background: var(--surface);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-out);
  transition: box-shadow 160ms ease, transform 160ms ease, filter 160ms ease;
}
.n-btn:hover:not(:disabled) { transform: translateY(-1px); }
.n-btn:active:not(:disabled) { box-shadow: var(--shadow-in); transform: none; }
.n-btn:focus-visible { outline: none; box-shadow: var(--shadow-out), 0 0 0 1.5px var(--accent); }
.n-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.v-primary { background: var(--accent); color: #fff; }
.v-primary:active:not(:disabled) { filter: brightness(0.94); box-shadow: var(--shadow-in); }

.s-md { height: 38px; padding: 0 18px; font-size: 13px; }
.s-sm { height: 30px; padding: 0 14px; font-size: 12px; }
</style>
