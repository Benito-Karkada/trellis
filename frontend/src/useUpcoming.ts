import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { UpcomingItem } from "./UpcomingPanel";

/** Fetches real deadlines; checklist writes never touch coursework progress. */
export function useUpcoming(courseId: number | null, contentVersion: unknown) {
  const [items, setItems] = useState<UpcomingItem[]>([]),
    [error, setError] = useState("");
  const [loading, setLoading] = useState(true),
    [pending, setPending] = useState<Set<number>>(new Set());
  const generation = useRef(0),
    writes = useRef(new Set<number>());
  const refresh = useCallback(async () => {
    if (!courseId || writes.current.size) return;
    const request = ++generation.current;
    try {
      const data = await api("upcoming/", undefined, courseId);
      if (request !== generation.current) return;
      setItems(data.items);
      setError("");
    } catch (e) {
      if (request === generation.current) setError((e as Error).message);
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [courseId]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, 60000);
    const focus = () => {
      void refresh();
    };
    window.addEventListener("focus", focus);
    return () => {
      generation.current++;
      clearInterval(timer);
      window.removeEventListener("focus", focus);
    };
  }, [refresh, contentVersion]);
  async function toggle(id: number, checked: boolean) {
    if (!courseId || writes.current.has(id)) return;
    const previous = items.find((item) => item.id === id)?.done;
    generation.current++;
    writes.current.add(id);
    setPending(new Set(writes.current));
    setItems((rows) =>
      rows.map((row) => (row.id === id ? { ...row, done: checked } : row)),
    );
    setError("");
    try {
      const result = await api(`upcoming/${id}/check/`, { checked }, courseId);
      setItems((rows) =>
        rows.map((row) =>
          row.id === id ? { ...row, done: result.done } : row,
        ),
      );
    } catch (e) {
      setItems((rows) =>
        rows.map((row) => (row.id === id ? { ...row, done: !!previous } : row)),
      );
      setError((e as Error).message);
    } finally {
      generation.current++;
      writes.current.delete(id);
      setPending(new Set(writes.current));
      setLoading(false);
    }
  }
  return { items, error, loading, pending, refresh, toggle };
}
