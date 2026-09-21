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

/** Total attempts allowed by the backend (the initial request is attempt 1). */
export const AUTO_RETRY_LIMITS = Object.freeze({
  transient: 3,
  rate_limited: 2,
  unknown: 3,
});

/** Compact current/maximum counter for a scheduled retry status pill. */
export function retryAttemptLabel(download) {
  const count = Number(download?.attempt_count || 0);
  const limit = AUTO_RETRY_LIMITS[download?.failure_kind];
  return count > 0 && limit ? `${count}/${limit}` : "";
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
