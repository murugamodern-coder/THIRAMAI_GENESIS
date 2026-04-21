/**
 * Map technical API errors to readable copy + suggested actions (UI only).
 * @param {Error & { status?: number; code?: string }} err
 */
export function friendlyApiError(err) {
  const status = err?.status;
  const raw = String(err?.message || err || 'Something went wrong');
  const lower = raw.toLowerCase();

  if (status === 401 || lower.includes('not authenticated') || lower.includes('unauthorized')) {
    return {
      title: 'Sign-in required',
      detail: 'Your session is missing or expired.',
      suggestion: 'Sign in again, then retry this action.',
    };
  }
  if (status === 403 || lower.includes('access denied') || lower.includes('forbidden')) {
    return {
      title: 'You don’t have permission',
      detail: raw,
      suggestion:
        'Ask an admin for the right role (e.g. manager for goals, admin for advanced controls), or try a different account.',
    };
  }
  if (status === 404) {
    return {
      title: 'Not found',
      detail: raw,
      suggestion: 'Refresh the job list or pick another job — it may have been removed.',
    };
  }
  if (status === 409) {
    return {
      title: 'Duplicate submission',
      detail: raw,
      suggestion: 'This request was already sent. Check recent jobs or use a new idempotency key if your client supports it.',
    };
  }
  if (status === 429 || lower.includes('quota') || lower.includes('rate')) {
    return {
      title: 'Temporarily limited',
      detail: raw,
      suggestion: 'Wait a few minutes, reduce concurrent goals, or upgrade your plan if applicable.',
    };
  }
  if (status === 503 || lower.includes('unavailable') || lower.includes('shutting down')) {
    return {
      title: 'Service busy or maintenance',
      detail: raw,
      suggestion: 'Retry shortly. If it persists, check deployment health and THIRAMAI safe mode.',
    };
  }
  if (lower.includes('timeout') || lower.includes('network') || lower.includes('fetch')) {
    return {
      title: 'Connection issue',
      detail: raw,
      suggestion: 'Check REACT_APP_API_URL, VPN, and that the API is running; then retry.',
    };
  }
  return {
    title: 'Request failed',
    detail: raw,
    suggestion: 'Retry once. If it keeps happening, copy the message and contact support.',
  };
}
