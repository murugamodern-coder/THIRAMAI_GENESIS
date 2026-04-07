let lastSnapshot = null;

export function setLiveSnapshot(snapshot) {
  lastSnapshot = snapshot || null;
}

export function getLiveSnapshot() {
  return lastSnapshot;
}

