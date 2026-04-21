/* Injected at build time via vite.config.js define (see __CC_APP_VERSION__, __CC_GIT_SHA__). */

export function getBuildInfo() {
  const version =
    typeof __CC_APP_VERSION__ !== "undefined" ? __CC_APP_VERSION__ : "dev";
  const gitSha = typeof __CC_GIT_SHA__ !== "undefined" ? __CC_GIT_SHA__ : "unknown";
  return { version, gitSha };
}
