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
