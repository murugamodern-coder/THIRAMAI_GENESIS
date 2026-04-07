/** Per-user first-run onboarding flag (localStorage). */

export function onboardingStorageKey(userId) {
  if (userId == null || userId === 0) return "thiramai_onboarding_done_guest";
  return `thiramai_onboarding_done_${userId}`;
}

export function isOnboardingDone(userId) {
  if (typeof localStorage === "undefined") return true;
  return localStorage.getItem(onboardingStorageKey(userId)) === "1";
}

export function setOnboardingDone(userId, done = true) {
  if (typeof localStorage === "undefined") return;
  if (done) localStorage.setItem(onboardingStorageKey(userId), "1");
  else localStorage.removeItem(onboardingStorageKey(userId));
}
