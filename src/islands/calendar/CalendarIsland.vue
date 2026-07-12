<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ApiError, useCalendar } from "./api";
import type { CalendarEvent } from "./types";
import type { Island } from "../../core/types";
import NButton from "../../ui/NButton.vue";

const props = defineProps<{ island: Island }>();
const api = useCalendar(props.island);
const events = ref<CalendarEvent[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

const dayKey = (iso: string) => {
  const date = new Date(iso);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
};

const groups = computed(() => {
  const grouped = new Map<string, CalendarEvent[]>();
  for (const event of events.value) {
    const key = dayKey(event.start);
    (grouped.get(key) ?? grouped.set(key, []).get(key)!).push(event);
  }
  return [...grouped.entries()];
});

function dayLabel(iso: string) {
  const date = new Date(iso);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  if (dayKey(iso) === dayKey(today.toISOString())) return "Today";
  if (dayKey(iso) === dayKey(tomorrow.toISOString())) return "Tomorrow";
  return new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "short" }).format(date);
}

function eventTime(event: CalendarEvent) {
  if (event.all_day) return "All day";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(event.start));
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    events.value = await api.listCalendarEvents();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="calendar-island" aria-labelledby="calendar-title">
    <header class="head">
      <div>
        <h2 id="calendar-title">Calendar</h2>
        <p>Upcoming · 14 days</p>
      </div>
      <NButton size="sm" variant="primary" :disabled="loading" @click="load">
        {{ loading ? "Syncing…" : "Sync" }}
      </NButton>
    </header>

    <div v-if="error" class="error" role="alert">
      <strong>Calendar unavailable</strong>
      <span>{{ error }}</span>
      <NButton size="sm" @click="load">Try again</NButton>
    </div>
    <p v-else-if="loading && !events.length" class="state">Loading calendar…</p>
    <p v-else-if="!events.length" class="state">Nothing scheduled in the next 14 days.</p>

    <div v-else class="days" :aria-busy="loading">
      <section v-for="[, items] in groups" :key="dayKey(items[0].start)" class="day">
        <div class="day-head">
          <h3>{{ dayLabel(items[0].start) }}</h3>
          <span>{{ items.length }} event{{ items.length === 1 ? "" : "s" }}</span>
        </div>
        <div class="event-list">
          <article v-for="(event, index) in items" :key="event.id" class="event">
            <time :datetime="event.start" :class="{ allDay: event.all_day }">{{ eventTime(event) }}</time>
            <span class="accent" :class="{ muted: index > 0 }" />
            <div class="event-copy">
              <div class="title">{{ event.title }}</div>
              <div v-if="event.location || event.calendar_name" class="meta">
                <span v-if="event.location">{{ event.location }}</span>
                <span>{{ event.calendar_name }}</span>
              </div>
            </div>
          </article>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.calendar-island { max-width: 760px; width: 100%; margin: 0 auto; }
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--sp-6); }
h2 { margin: 0; font: 600 24px var(--font-display); }
.head p { margin: 4px 0 0; color: var(--text-dim); font: 10px var(--font-mono); letter-spacing: .12em; text-transform: uppercase; }
.days { display: flex; flex-direction: column; gap: var(--sp-4); opacity: 1; transition: opacity 160ms ease; }
.days[aria-busy="true"] { opacity: .6; }
.day { padding: var(--sp-4); border-radius: var(--r-lg); background: var(--surface); box-shadow: var(--shadow-out); }
.day-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--sp-3); }
.day-head h3 { margin: 0; font: 600 15px var(--font-display); }
.day-head span { color: var(--text-dim); font: 10px var(--font-mono); }
.event-list { display: flex; flex-direction: column; gap: var(--sp-2); }
.event { display: grid; grid-template-columns: 58px 3px 1fr; gap: var(--sp-3); align-items: center; min-height: 46px; padding: 5px var(--sp-3); border-radius: var(--r-md); box-shadow: var(--shadow-in); }
time { color: var(--text-dim); font: 11px var(--font-mono); }
time.allDay { color: var(--accent); font-size: 9px; letter-spacing: .04em; text-transform: uppercase; }
.accent { width: 3px; height: 30px; border-radius: 2px; background: var(--accent); }
.accent.muted { background: var(--sh-dark); }
.event-copy { min-width: 0; }
.title { font-size: 13px; font-weight: 500; }
.meta { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-top: 3px; color: var(--text-dim); font: 10px var(--font-mono); }
.meta span + span::before { content: "·"; margin-right: var(--sp-2); }
.state { padding: var(--sp-6); color: var(--text-dim); text-align: center; font-size: 13px; }
.error { display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-2); padding: var(--sp-4); border-radius: var(--r-lg); box-shadow: var(--shadow-in); color: var(--accent); font-size: 13px; }
.error span { color: var(--text-dim); }
@media (max-width: 560px) { .event { grid-template-columns: 50px 3px 1fr; padding-inline: var(--sp-2); } }
</style>
