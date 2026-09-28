import { useRef, type KeyboardEvent, type PointerEvent } from 'react'

import { Button } from './Button'
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

export type Period = 'am' | 'pm'

/** A position on a 12-hour clock: hour 1 to 12, minute 0 to 59. */
export type ClockValue = { period: Period; hour: number; minute: number }

type Hand = 'hour' | 'minute'

type ClockFaceProps = {
  value: ClockValue
  /** The minutes a drag or an arrow key snaps to: 30, 5 or 1. */
  minuteStep: number
  onChange: (value: ClockValue) => void
}

// In the SVG's own units: a 200 x 200 face, radius 100.
const CENTRE = 100
const HOUR_HAND = 0.5
const MINUTE_HAND = 0.78
// Two hands closer than this share a direction, and the distance from the centre decides.
const OVERLAP_DEGREES = 15
const GRAB_BOUNDARY = (HOUR_HAND + MINUTE_HAND) / 2

const PERIODS: readonly [Period, string][] = [
  ['am', 'AM'],
  ['pm', 'PM'],
]

const HOURS = Array.from({ length: 12 }, (_, index) => index + 1)

/**
 * An analog clock input: drag either hand with a finger, a mouse or a pen, or focus a hand
 * and use the arrow keys, plus an AM/PM toggle. Controlled: it holds no question and calls
 * no API, and every change goes through `onChange`.
 *
 * The hands are independent (the minute hand passing 12 never moves the hour), and the hour
 * hand points exactly at its mark. Nothing in it is Hangul: the words the listener must
 * recognise by ear are never matchable by eye.
 */
export function ClockFace({ value, minuteStep, onChange }: ClockFaceProps) {
  const grabbed = useRef<Hand | null>(null)
  const hourAngle = hourToAngle(value.hour)
  const minuteAngle = minuteToAngle(value.minute)

  function moveHand(hand: Hand, angle: number): void {
    if (hand === 'hour') {
      onChange({ ...value, hour: angleToHour(angle) })
    } else {
      onChange({ ...value, minute: angleToMinute(angle, minuteStep) })
    }
  }

  function pointer(event: PointerEvent<HTMLDivElement>): { angle: number; reach: number } {
    const box = event.currentTarget.getBoundingClientRect()
    const cx = box.left + box.width / 2
    const cy = box.top + box.height / 2
    const radius = box.width / 2
    const reach = radius > 0 ? Math.hypot(event.clientX - cx, event.clientY - cy) / radius : 0
    return { angle: pointToAngle(event.clientX, event.clientY, cx, cy), reach }
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>): void {
    const { angle, reach } = pointer(event)
    let hand: Hand
    if (angleBetween(hourAngle, minuteAngle) < OVERLAP_DEGREES) {
      hand = reach <= GRAB_BOUNDARY ? 'hour' : 'minute'
    } else {
      hand = angleBetween(angle, hourAngle) <= angleBetween(angle, minuteAngle) ? 'hour' : 'minute'
    }
    grabbed.current = hand
    // jsdom has no pointer capture; every browser the app supports does.
    if (typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId)
    }
    moveHand(hand, angle)
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>): void {
    if (grabbed.current !== null) {
      moveHand(grabbed.current, pointer(event).angle)
    }
  }

  function release(): void {
    grabbed.current = null
  }

  function handleKey(hand: Hand, event: KeyboardEvent<SVGGElement>): void {
    const delta = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[event.key]
    if (delta === undefined) {
      return
    }
    event.preventDefault()
    if (hand === 'hour') {
      onChange({ ...value, hour: stepHour(value.hour, delta) })
    } else {
      onChange({ ...value, minute: stepMinute(value.minute, delta, minuteStep) })
    }
  }

  const minuteText = String(value.minute).padStart(2, '0')

  return (
    <div className="flex flex-col items-center gap-4">
      <div
        data-clock-face=""
        className="aspect-square w-full max-w-72 cursor-pointer touch-none select-none"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={release}
        onPointerCancel={release}
      >
        <svg viewBox="0 0 200 200" className="size-full overflow-visible">
          <circle cx={CENTRE} cy={CENTRE} r={98} className="fill-surface stroke-primary-soft" strokeWidth={4} />
          {HOURS.map((hour) => {
            const radians = (hourToAngle(hour) * Math.PI) / 180
            return (
              <text
                key={hour}
                x={CENTRE + 80 * Math.sin(radians)}
                y={CENTRE - 80 * Math.cos(radians)}
                textAnchor="middle"
                dominantBaseline="central"
                aria-hidden="true"
                className="fill-ink text-base font-bold"
              >
                {hour}
              </text>
            )
          })}
          <HandSlider
            name="Hour"
            angle={hourAngle}
            length={HOUR_HAND}
            width={8}
            colour="stroke-primary"
            min={1}
            max={12}
            now={value.hour}
            valueText={`${value.hour} o'clock`}
            onKeyDown={(event) => handleKey('hour', event)}
          />
          <HandSlider
            name="Minute"
            angle={minuteAngle}
            length={MINUTE_HAND}
            width={5}
            colour="stroke-ink"
            min={0}
            max={59}
            now={value.minute}
            valueText={`${value.minute} ${value.minute === 1 ? 'minute' : 'minutes'}`}
            onKeyDown={(event) => handleKey('minute', event)}
          />
          <circle cx={CENTRE} cy={CENTRE} r={6} className="fill-primary" />
        </svg>
      </div>

      <p className="font-display text-3xl text-ink tabular-nums">
        {value.hour}:{minuteText} {value.period === 'am' ? 'AM' : 'PM'}
      </p>

      <div role="group" aria-label="Morning or afternoon" className="flex gap-2">
        {PERIODS.map(([period, label]) => (
          <Button
            key={period}
            variant={value.period === period ? 'secondary' : 'subtle'}
            aria-pressed={value.period === period}
            onClick={() => onChange({ ...value, period })}
          >
            {label}
          </Button>
        ))}
      </div>
    </div>
  )
}

type HandSliderProps = {
  name: string
  angle: number
  length: number
  width: number
  colour: string
  min: number
  max: number
  now: number
  valueText: string
  onKeyDown: (event: KeyboardEvent<SVGGElement>) => void
}

/** One hand, drawn pointing up and rotated into place, and focusable as a slider. */
function HandSlider({ name, angle, length, width, colour, min, max, now, valueText, onKeyDown }: HandSliderProps) {
  const tip = CENTRE - length * CENTRE
  return (
    <g
      role="slider"
      tabIndex={0}
      aria-label={name}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={now}
      aria-valuetext={valueText}
      aria-orientation="horizontal"
      transform={`rotate(${angle} ${CENTRE} ${CENTRE})`}
      onKeyDown={onKeyDown}
      className="group cursor-grab outline-none"
    >
      <line x1={CENTRE} y1={CENTRE} x2={CENTRE} y2={tip} strokeWidth={width} strokeLinecap="round" className={colour} />
      <circle
        cx={CENTRE}
        cy={tip}
        r={11}
        strokeWidth={4}
        className="fill-accent stroke-transparent group-focus-visible:stroke-primary-strong"
      />
    </g>
  )
}
