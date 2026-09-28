/**
 * The clock's maths without a DOM (time-exercise T04). Each block pins one of the classic
 * silent clock bugs: a mirrored y axis, an hour of 0, a minute of 60.
 */

import { describe, expect, it } from 'vitest'

import {
  angleBetween,
  angleToHour,
  angleToMinute,
  hourToAngle,
  minuteToAngle,
  pointToAngle,
  stepHour,
  stepMinute,
} from './clockGeometry'

describe('pointToAngle, centre (100, 100), screen y downward', () => {
  it.each([
    [100, 0, 0],
    [200, 100, 90],
    [100, 200, 180],
    // A y-up implementation returns 90 here.
    [0, 100, 270],
  ])('(%d, %d) is %d degrees', (x, y, expected) => {
    expect(pointToAngle(x, y, 100, 100)).toBeCloseTo(expected)
  })
})

describe('angleToHour', () => {
  it.each([
    [0, 12],
    [90, 3],
    [180, 6],
    [270, 9],
    [14, 12],
    [16, 1],
    [345, 12],
  ])('%d degrees is hour %d', (angle, hour) => {
    expect(angleToHour(angle)).toBe(hour)
  })
})

describe('angleToMinute', () => {
  it.each([
    [5, 0, 0],
    [5, 90, 15],
    [5, 180, 30],
    [5, 270, 45],
    [5, 102, 15],
    [5, 108, 20],
    [5, 354, 0],
    [1, 102, 17],
    [1, 354, 59],
    [30, 80, 0],
    [30, 100, 30],
    [30, 300, 0],
  ])('step %d: %d degrees is minute %d', (step, angle, minute) => {
    expect(angleToMinute(angle, step)).toBe(minute)
  })
})

describe('round trips', () => {
  it('every hour survives angle and back', () => {
    for (let hour = 1; hour <= 12; hour += 1) {
      expect(angleToHour(hourToAngle(hour))).toBe(hour)
    }
  })

  it.each([30, 5, 1])('every minute on the grid of step %d survives angle and back', (step) => {
    for (let minute = 0; minute < 60; minute += step) {
      expect(angleToMinute(minuteToAngle(minute), step)).toBe(minute)
    }
  })
})

describe('angleBetween', () => {
  it.each([
    [0, 90, 90],
    [350, 10, 20],
    [10, 350, 20],
    [0, 180, 180],
  ])('%d and %d are %d apart', (a, b, expected) => {
    expect(angleBetween(a, b)).toBe(expected)
  })
})

describe('keyboard steps wrap without carrying', () => {
  it.each([
    [12, 1, 1],
    [1, -1, 12],
    [11, 1, 12],
    [6, -1, 5],
  ])('hour %d, step %d is %d', (hour, delta, expected) => {
    expect(stepHour(hour, delta)).toBe(expected)
  })

  it.each([
    [55, 1, 5, 0],
    [0, -1, 5, 55],
    [59, 1, 1, 0],
    [0, 1, 30, 30],
    [30, 1, 30, 0],
    // Off the grid (the step changed): from the nearest grid point.
    [7, 1, 5, 10],
  ])('minute %d, step %d at grid %d is %d', (minute, delta, step, expected) => {
    expect(stepMinute(minute, delta, step)).toBe(expected)
  })
})
