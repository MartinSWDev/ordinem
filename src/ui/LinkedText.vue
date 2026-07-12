<script setup lang="ts">
import { computed } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";

const props = defineProps<{ text: string }>();

type Seg = { t: "text"; v: string } | { t: "link"; label: string; href: string };

// Matches markdown links [label](url) and bare http(s) URLs.
const PATTERN = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s)]+)/g;

const segments = computed<Seg[]>(() => {
  const out: Seg[] = [];
  const text = props.text ?? "";
  let last = 0;
  for (const m of text.matchAll(PATTERN)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push({ t: "text", v: text.slice(last, idx) });
    if (m[2]) out.push({ t: "link", label: m[1], href: m[2] }); // markdown
    else out.push({ t: "link", label: m[3], href: m[3] }); // bare url
    last = idx + m[0].length;
  }
  if (last < text.length) out.push({ t: "text", v: text.slice(last) });
  return out;
});

function open(href: string) {
  openUrl(href).catch(() => {});
}
</script>

<template>
  <span class="linked-text"
    ><template v-for="(s, i) in segments" :key="i"
      ><a v-if="s.t === 'link'" class="lnk" @click.prevent="open(s.href)" :title="s.href">{{ s.label }}</a
      ><template v-else>{{ s.v }}</template></template
    ></span
  >
</template>

<style scoped>
.linked-text {
  white-space: pre-wrap;
  word-break: break-word;
}
.lnk {
  color: var(--accent);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>
