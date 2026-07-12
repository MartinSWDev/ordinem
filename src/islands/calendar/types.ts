// Calendar island — a normalized upcoming event.

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string | null;
  calendar_name: string;
}
