/** Formatting that matches the design: "R84 000.00", "Thursday, 26 November 2026", greetings by SA time. */

export const TIME_ZONE = "Africa/Johannesburg";

/** Whole cents -> "R84 000.00" (space thousands separator, as in the design). Never uses floats for the sum. */
export function rands(cents: number): string {
  const negative = cents < 0;
  const abs = Math.abs(Math.trunc(cents));
  const whole = Math.floor(abs / 100)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const fraction = (abs % 100).toString().padStart(2, "0");
  return `${negative ? "-" : ""}R${whole}.${fraction}`;
}

/** Basis points -> "15%" or "12.5%". */
export function percent(bp: number): string {
  const value = bp / 100;
  return `${Number.isInteger(value) ? value : value.toFixed(2).replace(/0+$/, "")}%`;
}

function parseDay(value: string | Date): Date {
  // A bare "YYYY-MM-DD" is a calendar day: pin it to midday UTC so no time zone can shift it.
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T12:00:00Z`);
  return typeof value === "string" ? new Date(value) : value;
}

export function longDate(value: string | Date): string {
  return new Intl.DateTimeFormat("en-ZA", {
    weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: TIME_ZONE,
  }).format(parseDay(value)).replace(/^(\w+) /, "$1, ");
}

/** "28 Nov" */
export function shortDate(value: string | Date): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: TIME_ZONE }).format(parseDay(value));
}

/** "28 November" */
export function dayMonth(value: string | Date): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", timeZone: TIME_ZONE }).format(parseDay(value));
}

/** "09:12" in South African time. */
export function clock(value: string | Date): string {
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TIME_ZONE }).format(
    parseDay(value),
  );
}

export function greeting(now: Date = new Date()): "Good morning" | "Good afternoon" | "Good evening" {
  const hour = Number(new Intl.DateTimeFormat("en-GB", { hour: "numeric", hour12: false, timeZone: TIME_ZONE }).format(now));
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export function firstName(fullName: string | null | undefined): string {
  return (fullName ?? "").trim().split(/\s+/)[0] ?? "";
}

export function initials(fullName: string | null | undefined): string {
  const parts = (fullName ?? "").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1]![0] : "")).toUpperCase() || "?";
}

/** Whole days from `from` to `to` (calendar days, SA time). */
export function daysBetween(from: string, to: string): number {
  return Math.round((parseDay(to).getTime() - parseDay(from).getTime()) / 86_400_000);
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "26 November 2026" */
export function fullDay(value: string | Date): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: TIME_ZONE }).format(parseDay(value));
}

/** "26 Nov 2026" */
export function shortDay(value: string | Date): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: TIME_ZONE }).format(parseDay(value));
}

/** Today's calendar day in South Africa, "YYYY-MM-DD". */
export function todaySA(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE }).format(now);
}

/** 430080 -> "420 KB" */
export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
