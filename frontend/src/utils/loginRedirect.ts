export function safeReturnPath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") ||
    value.includes("\\") || [...value].some(char => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127)) {
    return "/";
  }
  const url = new URL(value, "https://app.invalid");
  if (url.origin !== "https://app.invalid" || /^\/(?:login|register)(?:\/|$)/i.test(url.pathname)) {
    return "/";
  }
  return url.pathname + url.search + url.hash;
}

export function loginUrl(returnTo: string): string {
  const path = safeReturnPath(returnTo);
  return path === "/" ? "/login" : `/login?${new URLSearchParams({ returnTo: path })}`;
}

export function loginDestination(search: string): string {
  return safeReturnPath(new URLSearchParams(search).get("returnTo"));
}
