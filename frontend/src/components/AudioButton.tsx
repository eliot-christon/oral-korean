import { useEffect, useRef, useState } from 'react'
import { Button } from './Button'
import { ReplayIcon } from './icons'

type AudioButtonProps = {
  url: string
  /** The button's accessible name: it shows only an icon. */
  label: string
  /** Try to play as soon as it shows. Only attempted: phones block it until a tap. */
  autoPlay?: boolean
  /** The large round form (a session's word) or a small one (a row in a list). */
  size?: 'large' | 'small'
}

/**
 * A play button for a word's audio, with no native controls. Without `autoPlay` nothing is
 * fetched until it is pressed, so a list of words synthesises only those played.
 */
export function AudioButton({ url, label, autoPlay = false, size = 'large' }: AudioButtonProps) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (autoPlay) {
      audioRef.current?.play().catch(() => {})
    }
  }, [url, autoPlay])

  const large = size === 'large'
  return (
    <div className={large ? 'flex flex-col items-center gap-2' : 'flex flex-col items-center'}>
      <audio ref={audioRef} src={url} preload={autoPlay ? 'auto' : 'none'} onError={() => setFailed(true)} />
      <Button
        round={large}
        variant={large ? 'primary' : 'subtle'}
        aria-label={label}
        onClick={() => void audioRef.current?.play().catch(() => {})}
      >
        <ReplayIcon />
      </Button>
      {failed && <p className="text-sm font-bold text-muted">Audio unavailable.</p>}
    </div>
  )
}
