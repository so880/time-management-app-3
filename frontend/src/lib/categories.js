// カテゴリの色・ルーレット項目のタグ（各画面で別々に持っていたのをまとめた。2026-11-06）

// 予定・実績のカテゴリの色（今日タブのタイムライン・まとめ・週報）
export const CATEGORY_COLORS = {
  '大学': '#007AFF', '予定': '#AF52DE', '生活': '#34C759', '勉強': '#4CAF50',
  '気分転換': '#FF9F0A', '娯楽': '#FF375F', '睡眠': '#5E5CE6', '移動': '#8E8E93',
  'その他': '#64D2FF', '中断': '#FF9500',
}

// ルーレット項目の既定タグ [名前, アイコン]。追加タグは 🏷
export const ROULETTE_TAGS = [['就活', '💼'], ['大学', '🎓'], ['私用', '🏠'], ['その他', '📌']]
export const tagIcon = (tag, fallback = '🏷') => ROULETTE_TAGS.find(([name]) => name === tag)?.[1] ?? fallback
