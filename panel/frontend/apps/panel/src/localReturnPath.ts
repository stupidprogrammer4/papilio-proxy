import type { Router } from "vue-router";

/** Resolve a known application destination after login. */
export function localReturnPath(router: Router, candidate: unknown): string {
  if (typeof candidate !== "string" || !candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) return "/";
  const target = router.resolve(candidate);
  return target.matched.length > 0 && target.path !== "/login" ? target.fullPath : "/";
}
