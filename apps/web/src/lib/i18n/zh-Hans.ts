import type { Messages } from './en'

/* Simplified Chinese.
 *
 * Not a character-by-character conversion of zh-Hant: the vocabulary differs
 * where the two reading communities differ — 评价 rather than 評論 for a
 * review, 商家 rather than 店家 for the business, 二维码 rather than QR Code,
 * 生成 rather than 產生. Running an opencc-style conversion over the
 * Traditional file would produce text that is technically Simplified and
 * reads as translated-from-elsewhere.
 *
 * Same typographic rules as zh-Hant: full-width punctuation, a space either
 * side of Latin runs such as Google. 条 is the measure word for a written item.
 */
export const zhHans: Messages = {
  document: {
    title: '撰写评价',
  },

  loading: {
    label: '正在准备您的评价',
    text: '正在准备您的评价…',
  },

  unavailable: {
    link: {
      message: '此评价链接已失效。',
      advice: '请向商家咨询。',
    },
    session: {
      // 已过期, where the link above is 已失效 — see the note in zh-Hant.
      message: '此评价链接已过期。',
      advice: '请重新扫描商家的评价二维码。',
    },
    busy: {
      message: '此评价链接当前繁忙。',
      advice: '请在几分钟后重新扫描二维码。',
    },
  },

  error: {
    message: '出错了。',
    advice: '请重试。',
    retry: '重试',
  },

  announce: {
    generating: '正在撰写建议…',
    ready: (count: number) => `已准备 ${count} 条建议。`,
    added: (count: number) => `已在下方新增 ${count} 条建议。`,
    generateFailed: '当前无法生成新的建议。',
    opening: '正在打开 Google。',
  },

  suggestions: {
    heading: '这次的体验如何？',
    lead: '以下几个示例，可以帮助您撰写评价。',
    generating: '生成中…',
    generateMore: '生成更多建议',
    ownHint: '想自己写吗？',
    skip: '前往 Google →',
    authenticity: '请仅使用符合您真实体验的内容。发布前可以修改任何建议。',
  },

  card: {
    use: '使用这条评价',
  },

  menu: {
    open: '菜单',
    title: '菜单',
    close: '关闭菜单',
    language: '语言',
  },

  notice: {
    capReached: '简体中文的建议已达次数上限。',
    capReachedEmpty: '这次无法为您准备建议。',
    failed: '当前无法生成新的建议。',
    retry: '重试',
    writeOwn: '前往 Google 自己撰写 →',
  },

  editor: {
    heading: '改成您自己的话',
    lead: '前往 Google 前，您可以先修改这条建议。',
    textareaLabel: '您的评价',
    resetLabel: '还原为原始建议',
    emptyHint: '不会复制任何内容，您可以直接在 Google 上撰写评价。',
    copyHint: '我们会复制您的评价并打开 Google。请粘贴到评价框，选择星级评分，然后发布。',
    opening: '正在打开 Google…',
    continue: '前往 Google 评价',
    back: '← 选择其他建议',
    authenticity: '请仅使用符合您真实体验的内容。',
  },
}
