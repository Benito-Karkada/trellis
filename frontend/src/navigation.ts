import { useEffect, useRef, useState } from "react";

export type Route = {
  page: "courses" | "home" | "course" | "settings" | "gradebook" | "visualizer" | "discussions";
  courseId: number | null;
  lessonId: number | null;
  active: number | null;
  post: number | null;
  followup: number | null;
  category: string;
  mode: "student" | "config" | "preview";
};
const home: Route = {
  page: "courses",
  courseId: null,
  lessonId: null,
  active: null,
  post: null,
  followup: null,
  category: "content",
  mode: "student",
};
export function readRoute(hash = window.location.hash): Route {
  const [path, query = ""] = hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query);
  const id = (name: string) => {
    const value = params.get(name);
    return value && /^\d+$/.test(value) && Number(value) > 0
      ? Number(value)
      : null;
  };
  const page =
    path === "/courses" || !path || path === "/"
      ? "courses"
      : path === "/visualizer"
        ? "visualizer"
        : path === "/course"
          ? "course"
          : path === "/settings"
            ? "settings"
            : path === "/gradebook"
              ? "gradebook"
              : path === "/discussions"
                ? "discussions"
              : "home";
  const mode = params.get("mode");
  return {
    ...home,
    page,
    courseId: id("course"),
    lessonId: id("lesson"),
    active: id("activity"),
    post: id("post"),
    followup: id("followup"),
    category: params.get("category") || "content",
    mode: mode === "config" || mode === "preview" ? mode : "student",
  };
}
export function routeHref(route: Partial<Route>): string {
  const value = { ...home, courseId: readRoute().courseId, ...route };
  const params = new URLSearchParams();
  if (value.courseId) params.set("course", String(value.courseId));
  if (value.page === "discussions") {
    if (value.post) params.set("post", String(value.post));
    if (value.post && value.followup) params.set("followup", String(value.followup));
    return "#/discussions" + (params.size ? "?" + params.toString() : "");
  }
  if (value.page !== "course" && value.page !== "visualizer") {
    const path = value.page === "courses" ? "" : value.page;
    return "#/" + path + (params.size ? "?" + params.toString() : "");
  }
  if (value.lessonId) params.set("lesson", String(value.lessonId));
  if (value.active) params.set("activity", String(value.active));
  params.set("category", value.category);
  if (value.mode !== "student") params.set("mode", value.mode);
  return `#/${value.page}?` + params.toString();
}

export function useNavigation() {
  const [route, setState] = useState<Route>(() => readRoute());
  const guard = useRef<() => boolean>(() => true);
  const index = useRef<number>(window.history.state?.trellisIndex ?? 0);
  useEffect(() => {
    window.history.replaceState(
      { trellisIndex: index.current },
      "",
      routeHref(readRoute()),
    );
    const pop = (event: PopStateEvent) => {
      const nextIndex = event.state?.trellisIndex;
      if (nextIndex === index.current) return; // Return from a blocked Back/Forward.
      if (!guard.current()) {
        if (typeof nextIndex === "number")
          window.history.go(index.current - nextIndex);
        return;
      }
      index.current = typeof nextIndex === "number" ? nextIndex : index.current;
      setState(readRoute());
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    const href = routeHref(route);
    if (window.location.hash === href) return;
    index.current += 1;
    window.history.pushState({ trellisIndex: index.current }, "", href);
  }, [route]);
  const update = (next: Partial<Route>) =>
    setState((old) => ({ ...old, ...next }));
  return { route, update, guard };
}
