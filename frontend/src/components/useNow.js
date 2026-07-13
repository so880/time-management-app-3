// 1秒（既定）ごとに現在時刻(ms)を返すフック。タイマー表示用。
import { useEffect, useState } from 'react'

export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

// アラーム音（既存と同じ：矩形波440Hzを1.5秒）
export function playBeep() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    const actx = new Ctx()
    const osc = actx.createOscillator()
    osc.type = 'square'
    osc.frequency.setValueAtTime(440, actx.currentTime)
    osc.connect(actx.destination)
    osc.start()
    setTimeout(() => osc.stop(), 1500)
  } catch {
    /* 音が出せない環境では何もしない */
  }
}
