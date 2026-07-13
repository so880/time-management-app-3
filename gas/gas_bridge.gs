/**
 * FocusCafe ↔ Google 連携ブリッジ（Google Apps Script）
 * 貼り方は docs/SETUP_GOOGLE_SYNC.md を参照。
 *
 * 役割：
 *  1. sync_events … アプリから送られた予定を専用カレンダー「FocusCafe」に反映
 *     （説明欄の fcid: タグ付きイベントだけを入れ替えるので、手動の予定は消えない）
 *  2. log … iPhoneショートカットからの勉強記録を Googleドライブの
 *     FocusCafeSync/phone_inbox.json に追記（デスクトップが自動で取り込む）
 */

// ★ここを自分だけの合言葉に変える（アプリ側の設定と同じ文字列にする）
const TOKEN = 'CHANGE_ME';
const CAL_NAME = 'FocusCafe';
const FOLDER_NAME = 'FocusCafeSync';
const FILE_NAME = 'phone_inbox.json';

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return out({ ok: false, error: 'invalid json' });
  }
  if (body.token !== TOKEN) return out({ ok: false, error: 'bad token' });
  if (body.action === 'sync_events') return out(syncEvents(body));
  if (body.action === 'log') return out(appendLog(body));
  if (body.action === 'add') return out(appendItem(body));
  return out({ ok: false, error: 'unknown action' });
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function getCal() {
  const cals = CalendarApp.getCalendarsByName(CAL_NAME);
  if (cals.length) return cals[0];
  return CalendarApp.createCalendar(CAL_NAME);
}

function syncEvents(body) {
  const cal = getCal();
  const start = new Date(body.range_start + 'T00:00:00+09:00');
  const end = new Date(body.range_end + 'T23:59:59+09:00');
  // 既存の fcid: 付きイベント（＝このアプリが作ったもの）だけ削除して入れ替える
  cal.getEvents(start, end).forEach(function (ev) {
    if ((ev.getDescription() || '').indexOf('fcid:') >= 0) ev.deleteEvent();
  });
  let n = 0;
  (body.events || []).forEach(function (ev) {
    const desc = (ev.desc || '') + '\nfcid:' + ev.key;
    try {
      if (ev.allday) {
        if (ev.end && ev.end !== ev.start) {
          // 期間もの（例：5日間のインターン）。終了日は翌日0時（排他的）で渡す
          const endEx = new Date(ev.end + 'T00:00:00+09:00');
          endEx.setDate(endEx.getDate() + 1);
          cal.createAllDayEvent(ev.title, new Date(ev.start + 'T00:00:00+09:00'),
            endEx, { description: desc });
        } else {
          cal.createAllDayEvent(ev.title, new Date(ev.start + 'T00:00:00+09:00'),
            { description: desc });
        }
      } else {
        cal.createEvent(ev.title, new Date(ev.start + '+09:00'),
          new Date(ev.end + '+09:00'), { description: desc });
      }
      n++;
    } catch (err) { /* 1件の失敗で全体を止めない */ }
  });
  return { ok: true, created: n };
}

function _inboxFile() {
  const it = DriveApp.getFoldersByName(FOLDER_NAME);
  const folder = it.hasNext() ? it.next() : DriveApp.createFolder(FOLDER_NAME);
  const files = folder.getFilesByName(FILE_NAME);
  return files.hasNext() ? files.next() : folder.createFile(FILE_NAME, '[]');
}

/** iPhoneショートカットからの「支出」「単発予定」「課題メモ」を受け取り箱に追記する。
 *  支出:     { action:'add', type:'money', amount, category, detail }
 *  予定:     { action:'add', type:'event', title, date(yyyy-MM-dd), start(HH:mm), end(HH:mm) }
 *            複数日にまたがる予定は endDate(yyyy-MM-dd) も送る（date〜endDate の毎日に登録される）
 *  課題メモ: { action:'add', type:'asg_note', title(課題名の一部でOK), note, progress(0-100・空OK) }
 *            一致する課題があればメモ追記＋進捗更新、無ければ新しい課題として作成される
 *  デスクトップ側のアプリが5分おきに読み取って、手入力と同じ形で登録する。 */
function appendItem(body) {
  const file = _inboxFile();
  let arr = [];
  try { arr = JSON.parse(file.getBlob().getDataAsString() || '[]'); } catch (err) { arr = []; }
  arr.push({
    ts: Date.now() / 1000,
    type: String(body.type || ''),
    amount: body.amount,
    category: String(body.category || ''),
    detail: String(body.detail || ''),
    title: String(body.title || ''),
    date: String(body.date || ''),
    endDate: String(body.endDate || ''),
    start: String(body.start || ''),
    end: String(body.end || ''),
    note: String(body.note || ''),
    progress: String(body.progress || ''),
  });
  file.setContent(JSON.stringify(arr));
  return { ok: true, count: arr.length };
}

function appendLog(body) {
  const it = DriveApp.getFoldersByName(FOLDER_NAME);
  const folder = it.hasNext() ? it.next() : DriveApp.createFolder(FOLDER_NAME);
  const files = folder.getFilesByName(FILE_NAME);
  const file = files.hasNext() ? files.next() : folder.createFile(FILE_NAME, '[]');
  let arr = [];
  try { arr = JSON.parse(file.getBlob().getDataAsString() || '[]'); } catch (err) { arr = []; }
  arr.push({
    ts: Date.now() / 1000,
    task: String(body.task || '勉強'),
    minutes: Number(body.minutes) || 0,
    date: body.date || Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd'),
  });
  file.setContent(JSON.stringify(arr));
  return { ok: true, count: arr.length };
}
