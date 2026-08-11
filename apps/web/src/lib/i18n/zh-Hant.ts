import type { Messages } from './en'

/* Traditional Chinese.
 *
 * One word for a review throughout — 評論 — and one for the business — 店家.
 * The customer is handed to Google seconds after reading this, so a second
 * name for the same thing across that handover reads as a second task.
 *
 * Full-width punctuation (。，？), and a space either side of Latin runs such
 * as Google and QR Code, which is how the surrounding CJK text sets them.
 *
 * The count entries take the number and ignore plurality: Chinese has no
 * plural form, and 則 is the measure word for a written item.
 */
export const zhHant: Messages = {
  document: {
    title: '撰寫評論',
  },

  loading: {
    label: '正在準備您的評論',
    text: '正在準備您的評論…',
  },

  unavailable: {
    link: {
      message: '此評論連結已失效。',
      advice: '請向店家洽詢。',
    },
    session: {
      // 已過期, where the link above is 已失效: the customer's next step
      // differs, and a single wording for both would make one of the two
      // pieces of advice read as a non sequitur.
      message: '此評論連結已過期。',
      advice: '請重新掃描店家的評論 QR Code。',
    },
    busy: {
      message: '此評論連結目前忙碌中。',
      advice: '請於幾分鐘後重新掃描 QR Code。',
    },
  },

  error: {
    message: '發生錯誤。',
    advice: '請再試一次。',
    retry: '再試一次',
  },

  announce: {
    generating: '正在撰寫建議…',
    ready: (count: number) => `已準備 ${count} 則建議。`,
    added: (count: number) => `已在下方新增 ${count} 則建議。`,
    generateFailed: '目前無法產生新的建議。',
    opening: '正在開啟 Google。',
  },

  suggestions: {
    heading: '這次的體驗如何？',
    lead: '以下幾個範例，可以幫助您撰寫評論。',
    generating: '產生中…',
    generateMore: '產生更多建議',
    ownHint: '想自己寫嗎？',
    skip: '前往 Google →',
    authenticity: '請僅使用符合您真實體驗的內容。發布前可以修改任何建議。',
  },

  card: {
    use: '使用這則評論',
  },

  menu: {
    open: '選單',
    title: '選單',
    close: '關閉選單',
    language: '語言',
  },

  notice: {
    capReached: '繁體中文的建議已達次數上限。',
    capReachedEmpty: '這次無法為您準備建議。',
    failed: '目前無法產生新的建議。',
    retry: '再試一次',
    writeOwn: '前往 Google 自己撰寫 →',
  },

  editor: {
    heading: '改成您自己的話',
    lead: '前往 Google 前，您可以先修改這則建議。',
    textareaLabel: '您的評論',
    resetLabel: '還原成原始建議',
    emptyHint: '不會複製任何內容，您可以直接在 Google 上撰寫評論。',
    copyHint: '我們會複製您的評論並開啟 Google。請貼到評論欄位，選擇星級評分，然後發布。',
    opening: '正在開啟 Google…',
    continue: '前往 Google 評論',
    back: '← 選擇其他建議',
    authenticity: '請僅使用符合您真實體驗的內容。',
  },
}
