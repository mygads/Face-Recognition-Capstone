/** Guard against out-of-order async refreshes (polling vs user actions).

Each call to {@link next} starts a new generation. Await the work, then keep
the result only when {@link isCurrent} still holds: a slower earlier response
must never overwrite a newer one.
*/
/** Generation zero is never issued, so nothing is current before {@link next}. */
export function createRefreshEpoch(): {
  next: () => number
  isCurrent: (epoch: number) => boolean
} {
  let epoch = 0
  return {
    next: (): number => {
      epoch += 1
      return epoch
    },
    isCurrent: (candidate: number): boolean => candidate !== 0 && candidate === epoch,
  }
}
