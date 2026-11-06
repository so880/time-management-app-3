// ブラウザ通知（Web Notifications API・公式の標準的な使い方）
// タブが裏にあってもタイマー終了に気づけるようにする。

// 許可ダイアログは「ユーザー操作のタイミング」でしか出せないため、
// 集中モード開始ボタンなどのクリック時に呼ぶ。
export function ensureNotifyPermission() {
  try {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {})
    }
  } catch {
    /* 通知非対応の環境では何もしない */
  }
}

export function notify(title, body) {
  try {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(title, { body, silent: false })
    }
  } catch {
    /* 通知非対応の環境では何もしない */
  }
}
