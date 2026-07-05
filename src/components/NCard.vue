<script setup lang="ts"></script>

<template>
  <div class="n-card">
    <slot />
  </div>
</template>

<style scoped>
.n-card {
  background: var(--surface);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-out);
  padding: 20px;
}
</style>
