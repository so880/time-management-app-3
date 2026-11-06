// ホーム（HomeIos.jsx）の部品：時間帯と進み具合で変わる一言。HomeIos.jsx から分けた（中身は同じ）

// 進み具合（0〜100）と時間帯で変わる一言
export function dayComment(hour, rate) {
  if (hour < 5) return '夜ふかし中…明日にひびかない程度にね 🌙'
  if (hour < 11) {
    if (rate >= 60) return '朝からいい調子！この波に乗ろう 🌊'
    if (rate >= 20) return 'おはよう。いいスタート、切れてるよ ☕'
    return 'おはよう。まず1つだけ片づけよう ☕'
  }
  if (hour < 15) {
    if (rate >= 70) return '午前で大半クリア。強すぎる 💪'
    if (rate >= 40) return '折り返し。いいペース！'
    return '午後から巻き返そう。まずは小さいやつから 🍰'
  }
  if (hour < 19) {
    if (rate >= 90) return 'ほぼ勝ち確。あとひと押し ✨'
    if (rate >= 50) return '夕方のラストスパート！🔥'
    return '夜に残しすぎ注意。今のうちに1つ減らそう ⚠️'
  }
  if (rate >= 100) return '今日は完璧。ゆっくり休もう 🌙'
  if (rate >= 70) return 'あと少しで完走。えらい！🏁'
  if (rate >= 40) return '夜の追い込みタイム。最低ラインは守ろう 🌙'
  return '今日はもう欲張らず、最低ラインだけでも 🌙'
}
