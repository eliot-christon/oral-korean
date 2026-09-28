/**
 * The clock face's maths, apart from any DOM so its silent bugs are unit-tested: screen y
 * grows downward (a y-up `atan2` mirrors the clock), 12 must read as 12 and not 0, and a
 * minute that rounds up to 60 must wrap to 0.
 *
 * Angles are in degrees, clockwise from 12 o'clock, in [0, 360).
 */

/** The angle of the point (x, y) seen from the centre (cx, cy), in screen coordinates. */
export function pointToAngle(x: number, y: number, cx: number, cy: number): number {
  // atan2(dx, -dy): 0 straight up, growing clockwise, because screen y points down.
  const degrees = (Math.atan2(x - cx, cy - y) * 180) / Math.PI
  return normalise(degrees)
}

/** The hour mark nearest `angle`: 1 to 12, the top mark being 12. */
export function angleToHour(angle: number): number {
  return Math.round(normalise(angle) / 30) % 12 || 12
}

/** The minute nearest `angle` on the grid of `step`, wrapping 60 to 0. */
export function angleToMinute(angle: number, step: number): number {
  return snapMinute(normalise(angle) / 6, step)
}

/** Where the hour hand points for `hour` (1 to 12): exactly at its mark, no minute offset. */
export function hourToAngle(hour: number): number {
  return (hour % 12) * 30
}

/** Where the minute hand points for `minute` (0 to 59). */
export function minuteToAngle(minute: number): number {
  return minute * 6
}

/** The smaller of the two angles between `a` and `b`, 0 to 180. */
export function angleBetween(a: number, b: number): number {
  const difference = Math.abs(normalise(a) - normalise(b))
  return Math.min(difference, 360 - difference)
}

/** One hour up (`delta` 1) or down (-1), wrapping 12 to 1 and 1 to 12. */
export function stepHour(hour: number, delta: number): number {
  return (((hour - 1 + delta) % 12) + 12) % 12 + 1
}

/** One step of `step` minutes up or down from `minute`'s grid point, wrapping round the hour. */
export function stepMinute(minute: number, delta: number, step: number): number {
  return snapMinute(snapMinute(minute, step) + delta * step, step)
}

function snapMinute(minutes: number, step: number): number {
  const snapped = Math.round(minutes / step) * step
  return ((snapped % 60) + 60) % 60
}

function normalise(degrees: number): number {
  return ((degrees % 360) + 360) % 360
}
