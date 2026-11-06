// ホーム（HomeIos.jsx）の部品：目標の時間・分の ＋／− 入力。HomeIos.jsx から分けた（中身は同じ）

function Stepper({ label, value, onChange, min, max, step }) {
  const set = (v) => onChange(Math.max(min, Math.min(max, v)))
  return (
    <div className="ios-stepper">
      <span className="s-label">{label}</span>
      <button type="button" aria-label={`${label}を減らす`} onClick={() => set(value - step)}>−</button>
      <span className="s-value">{value}</span>
      <button type="button" aria-label={`${label}を増やす`} onClick={() => set(value + step)}>＋</button>
    </div>
  )
}

export default Stepper
