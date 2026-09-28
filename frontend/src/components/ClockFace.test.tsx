/**
 * The analog clock input (time-exercise T04), against the ticket's test contract.
 *
 * Same conventions as the other test files: `cleanup()` explicit in `afterEach`, no
 * jest-dom, no `user-event`. The clock is controlled, so each case asserts on the value
 * passed to the last `onChange` call. jsdom has no layout, so the face's
 * `getBoundingClientRect` is stubbed to a 200 x 200 box at (0, 0), and it has no
 * `setPointerCapture`, which the component must survive.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ClockFace, type ClockValue } from './ClockFace'

afterEach(() => {
  cleanup()
})

const HANGUL = /[가-힣]/

function renderClock(value: ClockValue, minuteStep = 5) {
  const onChange = vi.fn<(value: ClockValue) => void>()
  const view = render(<ClockFace value={value} minuteStep={minuteStep} onChange={onChange} />)
  const face = view.container.querySelector<HTMLElement>('[data-clock-face]')
  if (face === null) {
    throw new Error('no clock face')
  }
  face.getBoundingClientRect = () => new DOMRect(0, 0, 200, 200)
  return { ...view, onChange, face }
}

function lastValue(onChange: ReturnType<typeof renderClock>['onChange']): ClockValue {
  const call = onChange.mock.calls.at(-1)
  if (call === undefined) {
    throw new Error('onChange was never called')
  }
  return call[0]
}

function drag(face: HTMLElement, points: [number, number][], pointerType = 'mouse'): void {
  const [[x, y], ...rest] = points
  fireEvent.pointerDown(face, { clientX: x, clientY: y, pointerId: 1, pointerType })
  for (const [mx, my] of rest) {
    fireEvent.pointerMove(face, { clientX: mx, clientY: my, pointerId: 1, pointerType })
  }
}

describe('rendering and accessibility', () => {
  it('shows the digits 1 to 12 and no Hangul', () => {
    const { container } = renderClock({ period: 'am', hour: 12, minute: 0 })
    const dial = [...container.querySelectorAll('text')].map((text) => text.textContent)
    expect(dial).toEqual(['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'])
    expect(HANGUL.test(container.textContent ?? '')).toBe(false)
    expect(HANGUL.test(container.innerHTML)).toBe(false)
  })

  it('exposes the hour and the minute as named sliders', () => {
    renderClock({ period: 'pm', hour: 3, minute: 5 })
    const hour = screen.getByRole('slider', { name: /hour/i })
    const minute = screen.getByRole('slider', { name: /minute/i })
    expect(hour.getAttribute('aria-valuenow')).toBe('3')
    expect(minute.getAttribute('aria-valuenow')).toBe('5')
    expect(hour.getAttribute('aria-valuetext')).toBeTruthy()
    expect(minute.getAttribute('tabindex')).toBe('0')
  })

  it.each([
    [{ period: 'pm', hour: 3, minute: 5 } as ClockValue, '3:05 PM'],
    [{ period: 'am', hour: 12, minute: 0 } as ClockValue, '12:00 AM'],
  ])('reads out %o as %s', (value, expected) => {
    const { container } = renderClock(value)
    expect(container.textContent).toContain(expected)
  })
})

describe('keyboard', () => {
  it('hour 12, Arrow Up, is hour 1 with the rest unchanged', () => {
    const { onChange } = renderClock({ period: 'pm', hour: 12, minute: 40 })
    fireEvent.keyDown(screen.getByRole('slider', { name: /hour/i }), { key: 'ArrowUp' })
    expect(lastValue(onChange)).toEqual({ period: 'pm', hour: 1, minute: 40 })
  })

  it('hour 1, Arrow Down, is hour 12', () => {
    const { onChange } = renderClock({ period: 'am', hour: 1, minute: 0 })
    fireEvent.keyDown(screen.getByRole('slider', { name: /hour/i }), { key: 'ArrowDown' })
    expect(lastValue(onChange)).toEqual({ period: 'am', hour: 12, minute: 0 })
  })

  it('minute 55, Arrow Up, wraps to 0 without carrying into the hour', () => {
    const { onChange } = renderClock({ period: 'am', hour: 3, minute: 55 })
    fireEvent.keyDown(screen.getByRole('slider', { name: /minute/i }), { key: 'ArrowUp' })
    expect(lastValue(onChange)).toEqual({ period: 'am', hour: 3, minute: 0 })
  })

  it('minute 0, Arrow Down, wraps to 55 with the hour unchanged', () => {
    const { onChange } = renderClock({ period: 'am', hour: 3, minute: 0 })
    fireEvent.keyDown(screen.getByRole('slider', { name: /minute/i }), { key: 'ArrowDown' })
    expect(lastValue(onChange)).toEqual({ period: 'am', hour: 3, minute: 55 })
  })

  it('Arrow Right and Left move like Up and Down', () => {
    const { onChange } = renderClock({ period: 'am', hour: 3, minute: 10 })
    const minute = screen.getByRole('slider', { name: /minute/i })
    fireEvent.keyDown(minute, { key: 'ArrowRight' })
    expect(lastValue(onChange).minute).toBe(15)
    fireEvent.keyDown(minute, { key: 'ArrowLeft' })
    expect(lastValue(onChange).minute).toBe(5)
  })

  it('step 1: 59, Arrow Up, is 0', () => {
    const { onChange } = renderClock({ period: 'am', hour: 3, minute: 59 }, 1)
    fireEvent.keyDown(screen.getByRole('slider', { name: /minute/i }), { key: 'ArrowUp' })
    expect(lastValue(onChange).minute).toBe(0)
  })

  it('step 30: 0 goes to 30, then 30 back to 0', () => {
    const onChange = vi.fn<(value: ClockValue) => void>()
    const { rerender } = render(
      <ClockFace value={{ period: 'am', hour: 3, minute: 0 }} minuteStep={30} onChange={onChange} />,
    )
    fireEvent.keyDown(screen.getByRole('slider', { name: /minute/i }), { key: 'ArrowUp' })
    expect(lastValue(onChange).minute).toBe(30)
    rerender(<ClockFace value={{ period: 'am', hour: 3, minute: 30 }} minuteStep={30} onChange={onChange} />)
    fireEvent.keyDown(screen.getByRole('slider', { name: /minute/i }), { key: 'ArrowUp' })
    expect(lastValue(onChange).minute).toBe(0)
  })

  it('ignores other keys', () => {
    const { onChange } = renderClock({ period: 'am', hour: 3, minute: 0 })
    fireEvent.keyDown(screen.getByRole('slider', { name: /minute/i }), { key: 'a' })
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('AM/PM', () => {
  it('clicking PM changes only the period', () => {
    const { onChange } = renderClock({ period: 'am', hour: 3, minute: 40 })
    fireEvent.click(screen.getByRole('button', { name: 'PM' }))
    expect(lastValue(onChange)).toEqual({ period: 'pm', hour: 3, minute: 40 })
  })

  it('the pressed state follows the value', () => {
    const onChange = vi.fn<(value: ClockValue) => void>()
    const { rerender } = render(
      <ClockFace value={{ period: 'am', hour: 3, minute: 40 }} minuteStep={5} onChange={onChange} />,
    )
    expect(screen.getByRole('button', { name: 'AM' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'PM' }).getAttribute('aria-pressed')).toBe('false')
    rerender(<ClockFace value={{ period: 'pm', hour: 3, minute: 40 }} minuteStep={5} onChange={onChange} />)
    expect(screen.getByRole('button', { name: 'AM' }).getAttribute('aria-pressed')).toBe('false')
    expect(screen.getByRole('button', { name: 'PM' }).getAttribute('aria-pressed')).toBe('true')
  })
})

describe('dragging, value 3:40 AM (hour hand at 90 degrees, minute hand at 240)', () => {
  const VALUE: ClockValue = { period: 'am', hour: 3, minute: 40 }

  it.each(['mouse', 'touch', 'pen'])('a %s drag near the minute hand sets the minute', (pointerType) => {
    const { onChange, face } = renderClock(VALUE)
    drag(
      face,
      [
        [0, 100],
        [100, 200],
      ],
      pointerType,
    )
    expect(lastValue(onChange)).toEqual({ period: 'am', hour: 3, minute: 30 })
  })

  it('a drag on the hour hand sets the hour', () => {
    const { onChange, face } = renderClock(VALUE)
    drag(face, [
      [200, 100],
      [100, 200],
    ])
    expect(lastValue(onChange)).toEqual({ period: 'am', hour: 6, minute: 40 })
  })

  it('after pointer up, a move changes nothing', () => {
    const { onChange, face } = renderClock(VALUE)
    drag(face, [
      [0, 100],
      [100, 200],
    ])
    fireEvent.pointerUp(face, { clientX: 100, clientY: 200, pointerId: 1 })
    onChange.mockClear()
    fireEvent.pointerMove(face, { clientX: 200, clientY: 100, pointerId: 1 })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('a move with no pointer down changes nothing', () => {
    const { onChange, face } = renderClock(VALUE)
    fireEvent.pointerMove(face, { clientX: 200, clientY: 100, pointerId: 1 })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('the minute hand dragged past 12 and over the hour hand keeps the hour and stays grabbed', () => {
    const { onChange, face } = renderClock(VALUE)
    drag(face, [
      [0, 100],
      [100, 0],
      [200, 100],
    ])
    expect(lastValue(onChange)).toEqual({ period: 'am', hour: 3, minute: 15 })
    expect(onChange.mock.calls.every(([value]) => value.hour === 3)).toBe(true)
  })
})

describe('overlapping hands, value 12:00 AM', () => {
  const VALUE: ClockValue = { period: 'am', hour: 12, minute: 0 }

  it('a grab inside the hour hand length moves the hour', () => {
    const { onChange, face } = renderClock(VALUE)
    drag(face, [
      [100, 80],
      [200, 100],
    ])
    expect(lastValue(onChange)).toEqual({ period: 'am', hour: 3, minute: 0 })
  })

  it('a grab beyond it moves the minute', () => {
    const { onChange, face } = renderClock(VALUE)
    drag(face, [
      [100, 5],
      [200, 100],
    ])
    expect(lastValue(onChange)).toEqual({ period: 'am', hour: 12, minute: 15 })
  })
})

describe('touch panning', () => {
  it('the face disables browser panning', () => {
    const { face } = renderClock({ period: 'am', hour: 12, minute: 0 })
    expect(face.classList.contains('touch-none')).toBe(true)
  })

  it('jsdom has no setPointerCapture, and a drag does not throw', () => {
    const { face } = renderClock({ period: 'am', hour: 12, minute: 0 })
    expect('setPointerCapture' in face).toBe(false)
    expect(() => drag(face, [[100, 5]])).not.toThrow()
  })
})
