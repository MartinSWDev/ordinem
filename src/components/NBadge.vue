<script setup lang="ts">
defineProps<{
  /** dot colour intent */
  tone?: "accent" | "success" | "muted";
  /** pulse the dot (live/processing states) */
  pulse?: boolean;
}>();
</script>

<template>
  <span class="n-badge" :class="`tone-${tone ?? 'muted'}`">
    <span class="dot" :class="{ pulse }" />
    <slot />
  </span>
</template>

<style scoped>
.n-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 4px 9px;
  border-radius: var(--r-pill);
  background: var(--surface);
  box-shadow: var(--shadow-in);
  color: var(--text-dim);
  white-space: nowrap;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex: none;
}
.tone-accent {
  color: var(--accent);
}
.tone-success {
  color: var(--success);
}
.dot.pulse {
  animation: ndsPulse 1.6s infinite;
}
@keyframes ndsPulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}
</style>
