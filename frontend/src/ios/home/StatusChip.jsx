// ホーム（HomeIos.jsx）の部品：上部の状態チップ。HomeIos.jsx から分けた（中身は同じ）

// 上部の状態チップ（押すとその画面へ）
function StatusChip({ icon, label, tone, onClick, title }) {
  return (
    <button type="button" className={'status-chip' + (tone ? ' ' + tone : '')} onClick={onClick} title={title}>
      <span className="sc-icon" aria-hidden="true">{icon}</span>
      <span className="sc-label">{label}</span>
    </button>
  )
}

export default StatusChip
