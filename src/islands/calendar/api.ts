import { islandClient } from "../../core/api";
import type { Island } from "../../core/types";
import type { CalendarEvent } from "./types";

export { ApiError } from "../../core/api";

/** Calendar-island client: a single read-only feed off the island's base. */
export function useCalendar(island: Island) {
  const { request } = islandClient(island);
  return {
    listCalendarEvents: () => request<CalendarEvent[]>("GET", ""),
  };
}
