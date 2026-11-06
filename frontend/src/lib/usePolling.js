// 定期読み込みのフック：fn を「すぐ1回」＋「intervalMs ごと」に呼ぶ。
// 各画面に同じ形（let alive = true … setInterval … return () => { alive = false; clearInterval(id) }）が
// 何か所もあったので1つにまとめた。
//   - fn には isAlive() を渡す。画面を閉じた（アンマウントした）あとに届いた結果で state を書き換えないよう、
//     非同期の結果を反映する前に isAlive() を確かめる
//   - deps が変わったら、タイマーを張り直してすぐ1回読み直す（useEffect の依存配列と同じ意味）
//   - fn は ref で最新のものを呼ぶので、呼び出し側で useCallback にしなくてよい
// 使い方：usePolling((isAlive) => api.getX().then((x) => { if (isAlive()) setX(x) }).catch(() => {}), 60000, [])
import { useEffect, useRef } from 'react'

export function usePolling(fn, intervalMs, deps = []) {
  const fnRef = useRef(fn)
  // 描画のたびに最新の fn を覚えておく（下のタイマーより先に実行されるよう、こちらを先に書く）
  useEffect(() => {
    fnRef.current = fn
  })

  useEffect(() => {
    let alive = true
    const isAlive = () => alive
    const run = () => fnRef.current(isAlive)
    run()
    const id = setInterval(run, intervalMs)
    return () => { alive = false; clearInterval(id) }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 張り直す条件は呼び出し側が deps で決める（useEffect と同じ）
  }, [intervalMs, ...deps])
}
