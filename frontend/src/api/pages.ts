import type { List } from "./client";

// A record may move between pages while an analysis is running. Keep one row per ID.
export function pageItems<T extends { id: string }>(
  pages: List<T>[] | undefined,
): T[] {
  return Array.from(
    new Map(
      pages?.flatMap((p) => p.items).map((item) => [item.id, item]),
    ).values(),
  );
}
export function nextPage<T>(
  last: List<T>,
  _pages: List<T>[],
  _cursor: string | null,
  cursors: (string | null)[],
) {
  return last.next_cursor && !cursors.includes(last.next_cursor)
    ? last.next_cursor
    : undefined;
}
