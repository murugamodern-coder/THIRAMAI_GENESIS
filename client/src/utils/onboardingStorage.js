const KEY = 'thiramai_onboarding_v1';

function defaultState() {
  return {
    dismissed: false,
    firstGoalDone: false,
    resultsSeen: false,
    dashboardSeen: false,
  };
}

export function loadOnboarding() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return defaultState();
    const o = JSON.parse(raw);
    return { ...defaultState(), ...o };
  } catch {
    return defaultState();
  }
}

export function saveOnboarding(patch) {
  try {
    const next = { ...loadOnboarding(), ...patch };
    localStorage.setItem(KEY, JSON.stringify(next));
    return next;
  } catch {
    return loadOnboarding();
  }
}
