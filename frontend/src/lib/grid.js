/**
 * Pure grid helpers, kept out of App.svelte so they can be tested.
 *
 * Both of these shipped broken this session and the breakage was found by a
 * person looking at a screenshot: names truncated from the wrong end, and a tab
 * badge that called 262 stopped rows "in progress".
 */

/**
 * Statuses that mean the item is live in the queue — transferring or waiting
 * its turn. `stopped` and `failed` sit in the list but nothing is happening to
 * them, and counting them as progress made an idle queue look like a hung one.
 */
export const ACTIVE_STATUSES = [
  "downloading",
  "parsing",
  "proxying",
  "waiting",
  "pending",
];

/**
 * Whether a row is doing something, from whatever case the API/SSE used.
 *
 * Deliberately narrower than App.svelte's `isActiveStatus`, which mirrors the
 * backend's /downloads/active filter and counts `failed` as active because a
 * failed row still belongs in that list. "Live" here means moving, which is a
 * different question and the one the badge answers.
 */
export function isLiveStatus(status) {
  return ACTIVE_STATUSES.includes(String(status || "").toLowerCase());
}

/** How many of `rows` are actually moving. */
export function countLive(rows) {
  return (rows || []).filter((row) => isLiveStatus(row && row.status)).length;
}

/** Sum the active statuses out of an `{status: count}` map from /history/stats. */
export function countActiveByStatus(byStatus) {
  return ACTIVE_STATUSES.reduce(
    (sum, key) => sum + ((byStatus && byStatus[key]) || 0),
    0,
  );
}

/** Whether a failed or queue-parked row has an automatic retry scheduled. */
export function hasScheduledRetry(download, now = Date.now()) {
  const status = String(download?.status || "").toLowerCase();
  return Boolean(
    (status === "failed" || status === "pending") &&
      download?.next_retry_at &&
      new Date(download.next_retry_at).getTime() > now,
  );
}

/**
 * A row parked behind an earlier row of the same host. The host is tried one
 * row at a time, so only the head of the line carries the retry countdown.
 */
export function isQueuedBehind(download, now = Date.now()) {
  return hasScheduledRetry(download, now) && Number(download?.queue_position) > 1;
}

/**
 * Waits at least this long are shown as the clock time of the retry, not a
 * countdown. A 1fichier quota waits for the next Paris midnight, and "827:28"
 * on screen reads like a bug rather than "tomorrow morning".
 */
export const RETRY_CLOCK_AFTER_SECONDS = 3600;

/** Whether the retry is far enough away to show as a time of day. */
export function showsRetryClock(download, now = Date.now()) {
  if (!download?.next_retry_at) return false;
  return new Date(download.next_retry_at).getTime() - now >= RETRY_CLOCK_AFTER_SECONDS * 1000;
}

/** "07:10", or "tomorrow 07:10" / "내일 07:10" when the retry is on a later day. */
export function retryClockLabel(nextRetryAt, now = Date.now(), lang = "en") {
  const at = new Date(nextRetryAt);
  const time = at.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit", hour12: false });
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOfDay(at) - startOfDay(new Date(now))) / 86400000);
  if (days === 0) return time;
  const day = new Intl.RelativeTimeFormat(lang, { numeric: "auto" }).format(days, "day");
  return `${day} ${time}`;
}

/**
 * Total attempts allowed by the backend (the initial request is attempt 1).
 * Mirrors `_MAX_AUTO_RETRY_ATTEMPTS` for every kind that retries on its own;
 * backend/tests/test_frontend_retry_limits.py fails if the two drift.
 */
export const AUTO_RETRY_LIMITS = Object.freeze({
  transient: 2,
  slot_busy: 4,
});

/** Compact current/maximum counter for a scheduled retry status pill. */
export function retryAttemptLabel(download) {
  const count = Number(download?.attempt_count || 0);
  const limit = AUTO_RETRY_LIMITS[download?.failure_kind];
  return count > 0 && limit ? `${count}/${limit}` : "";
}

/**
 * A failed row is named by what the person can do about it. Only a failure the
 * app cannot explain stays the plain red "failed", so red means "broken" and
 * every other colour means "nothing is wrong with the app".
 */
const FAILURE_GROUPS = Object.freeze({
  source_unconfirmed: { key: "failed_source_gone", tone: "gone" },
  dead: { key: "failed_source_gone", tone: "gone" },
  auth_required: { key: "failed_needs_human", tone: "human" },
  slot_busy: { key: "failed_wait", tone: "wait" },
  rate_limited: { key: "failed_wait", tone: "wait" },
  daily_quota: { key: "failed_wait", tone: "wait" },
  blocked: { key: "failed_host_refused", tone: "refused" },
  proxy_blocked: { key: "failed_host_refused", tone: "refused" },
  cloudflare: { key: "failed_host_refused", tone: "refused" },
});

export function failureStatusKey(download) {
  return FAILURE_GROUPS[download?.failure_kind]?.key ?? "download_failed";
}

/** CSS tone for the failed pill; empty for the plain red failure. */
export function failureTone(download) {
  return FAILURE_GROUPS[download?.failure_kind]?.tone ?? "";
}

/**
 * Stable server page size for each responsive layout.
 *
 * Mobile browsers change `innerHeight` while their address bar collapses on
 * scroll. Deriving page size from height therefore made rows appear/disappear
 * simply by scrolling. Width only changes when the layout actually changes.
 */
export function itemsPerPageForWidth(width) {
  if (!Number.isFinite(width) || width <= 0) return 10;
  if (width < 768) return 8;
  if (width < 1024) return 10;
  return 15;
}

/**
 * Shorten a release name from the middle.
 *
 * The meaning sits at both ends: the title in front, and
 * `[titleId][version][Base|UPD][region].rar` behind. CSS ellipsis only cuts the
 * back, which is exactly the half that tells two builds of one game apart — so
 * a phone showed a long prefix and nothing usable.
 */
export function truncateMiddle(name, cap) {
  if (!name || name.length <= cap) return name;
  // Biased toward the tail, since that is where the disambiguating metadata is.
  const tail = Math.max(12, Math.floor(cap * 0.45));
  const head = cap - tail - 1;
  return `${name.slice(0, head)}…${name.slice(-tail)}`;
}

/** Fit both ends to the actual cell width, using the renderer's font metrics. */
export function fitFilename(name, width, measure) {
  if (!name || measure(name) <= width) return name;
  const chars = Array.from(name);
  let result = measure("…") <= width ? "…" : "";
  let low = 2;
  let high = chars.length - 1;
  while (low <= high) {
    const kept = Math.floor((low + high) / 2);
    const tail = Math.min(kept - 1, Math.max(12, Math.floor(kept * 0.45)));
    const candidate = `${chars.slice(0, kept - tail).join("")}…${chars.slice(-tail).join("")}`;
    if (measure(candidate) <= width) {
      result = candidate;
      low = kept + 1;
    } else {
      high = kept - 1;
    }
  }
  return result;
}
