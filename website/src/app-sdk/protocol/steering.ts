// kiro-cli emits a steering acknowledgment inline in the model's output when it
// consumes a mid-turn steer: `[STEERING steer-<id>: <what it did in response>]`.
// Showing that raw marker is ugly; instead we pull it out and render it as a
// distinct "Steered" chip (mirrors KiRoom's stripSteeringTag display-parity).
// The id part is `steer-<hex>` (no ']' or ':'). The summary is model-written and
// can hold a markdown link, `[PR #7](url)`, so it ends at the ']' that balances
// the marker's own '['. A summary whose brackets never balance ends at the first
// ']' after the head, as it always did.
const STEER_ACK_HEAD_RE = /\[STEERING\s+steer-[^\]:]+:/g

/** The index of the ']' that balances each '[' that has one. One pass, so a reply
 *  full of brackets stays linear. */
function balancedClosers(content: string): Map<number, number> {
  const closers = new Map<number, number>()
  const open: number[] = []
  for (let i = 0; i < content.length; i++) {
    if (content[i] === '[') open.push(i)
    else if (content[i] === ']') {
      const opener = open.pop()
      if (opener !== undefined) closers.set(opener, i)
    }
  }
  return closers
}

/** Append `slice`, which follows a removed marker, without its leading newlines beyond the
 *  one blank line the seam needs. Text elsewhere is never touched, so a code block keeps
 *  every blank line it was written with. */
function joinAtSeam(kept: string, slice: string): string {
  let trailing = 0
  while (trailing < 2 && kept[kept.length - 1 - trailing] === '\n') trailing++
  let leading = 0
  while (slice[leading] === '\n') leading++
  const keep = Math.min(leading, 2 - trailing)
  return kept + slice.slice(leading - keep)
}

export function extractSteeringAcks(content: string): { cleaned: string; acks: string[] } {
  const acks: string[] = []
  const lastClose = content.lastIndexOf(']')
  const closers = balancedClosers(content)
  let cleaned = ''
  let pos = 0
  let afterMarker = false
  for (const head of content.matchAll(STEER_ACK_HEAD_RE)) {
    const start = head.index
    if (start > lastClose) break
    // A head inside a marker already removed is part of that marker's summary.
    if (start < pos) continue
    const summaryStart = start + head[0].length
    const close = closers.get(start) ?? content.indexOf(']', summaryStart)
    const s = content.slice(summaryStart, close).trim()
    if (s) acks.push(s)
    const before = content.slice(pos, start)
    cleaned = afterMarker ? joinAtSeam(cleaned, before) : cleaned + before
    afterMarker = true
    pos = close + 1
  }
  const rest = content.slice(pos)
  cleaned = afterMarker ? joinAtSeam(cleaned, rest) : cleaned + rest
  return { cleaned: cleaned.trimEnd(), acks }
}
