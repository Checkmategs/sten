export type PercentMotion = {
  value: number
}

export function createPercentMotion(): PercentMotion {
  return { value: 0 }
}

const TRACK_PER_SEC = 12
const FINISH_PER_SEC = 18
const GLIDE_PER_SEC = 0.85
const GLIDE_AHEAD = 6

/** Move the on-screen percent toward the server value without snapping. */
export function advanceDisplayedPercent(
  state: PercentMotion,
  goal: number,
  dt: number,
  live: boolean,
): number {
  const target = Math.max(0, Math.min(100, goal))
  const step = Math.max(0, dt)
  if (target + 0.4 < state.value) {
    state.value = target
    return state.value
  }
  if (state.value < target - 0.02) {
    const speed = target >= 100 ? FINISH_PER_SEC : TRACK_PER_SEC
    state.value = Math.min(target, state.value + speed * step)
    return state.value
  }
  if (live && target < 100) {
    const ceiling = Math.min(99, target + GLIDE_AHEAD)
    if (state.value < ceiling) {
      state.value = Math.min(ceiling, state.value + GLIDE_PER_SEC * step)
    }
  }
  return state.value
}
