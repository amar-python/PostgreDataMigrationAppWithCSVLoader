import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** "27 Oct 2026, 19:33" in the viewer's time zone (#119). Pass timeZone for tests. */
export function formatLocalTime(iso: string | number, timeZone?: string): string {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZone,
    })
      .formatToParts(new Date(iso))
      .map((x) => [x.type, x.value]),
  );
  return `${p.day} ${p.month} ${p.year}, ${p.hour}:${p.minute}`;
}

/** "2026-10-27 08:33:05 UTC", kept as the tooltip for audit (#119). */
export function formatUtc(iso: string | number): string {
  return `${new Date(iso).toISOString().replace("T", " ").slice(0, 19)} UTC`;
}
