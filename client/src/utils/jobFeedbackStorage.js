const KEY = 'thiramai_job_feedback_v1';

function readAll() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return {};
    const o = JSON.parse(raw);
    return o && typeof o === 'object' ? o : {};
  } catch {
    return {};
  }
}

function writeAll(obj) {
  try {
    localStorage.setItem(KEY, JSON.stringify(obj));
  } catch {
    /* ignore quota */
  }
}

export function getJobFeedback(jobId) {
  if (!jobId) return null;
  const all = readAll();
  return all[jobId] || null;
}

export function setJobFeedback(jobId, payload) {
  if (!jobId) return;
  const all = readAll();
  all[jobId] = {
    ...payload,
    updated_ts: Date.now(),
  };
  writeAll(all);
}
