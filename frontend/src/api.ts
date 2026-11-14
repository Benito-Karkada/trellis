import { readRoute } from "./navigation";
export function csrfToken() {
  return (
    document.cookie
      .split("; ")
      .find((x) => x.startsWith("csrftoken="))
      ?.split("=")[1] || ""
  );
}

function courseHeaders(id: number | null): Record<string, string> {
  return id ? { "X-Trellis-Course": String(id) } : {};
}
export async function api(
  path: string,
  body?: unknown,
  courseId = readRoute().courseId,
) {
  const response = await fetch("/api/" + path, {
    credentials: "same-origin",
    headers: {
      ...courseHeaders(courseId),
      ...(body === undefined
        ? {}
        : { "Content-Type": "application/json", "X-CSRFToken": csrfToken() }),
    },
    ...(body === undefined
      ? {}
      : { method: "POST", body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw Error(data.error || `Request failed (${response.status}).`);
  return data;
}

export async function upload(
  path: string,
  body: FormData,
  courseId = readRoute().courseId,
) {
  const response = await fetch("/api/" + path, {
    method: "POST",
    credentials: "same-origin",
    headers: { ...courseHeaders(courseId), "X-CSRFToken": csrfToken() },
    body,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw Error(data.error || `Request failed (${response.status}).`);
  return data;
}

export async function download(
  path: string,
  filename: string,
  courseId = readRoute().courseId,
) {
  const response = await fetch("/api/" + path, {
    credentials: "same-origin",
    headers: courseHeaders(courseId),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Error(data.error || `Request failed (${response.status}).`);
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
