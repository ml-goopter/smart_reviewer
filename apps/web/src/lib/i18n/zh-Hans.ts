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

  /* The internal crawler, in the operator's register rather than the
   * customer's. 商户 for a prospect, as zh-Hant uses 商戶 — the operator is
   * looking at a row in a table, not at somewhere they just ate. 搜索 rather
   * than zh-Hant's 搜尋, and 网址 rather than 網址, which is the same
   * vocabulary split the customer screens already make. */
  leads: {
    title: '商户开发工具',
    viewsLabel: '商户开发工具视图',
    tabs: {
      search: '搜索',
      saved: '已保存',
    },
    loading: '加载中…',
    edit: '编辑',
    copyUrl: '复制网址',
    noUrl: '无网址',

    categories: {
      restaurant: '餐厅',
      cafe: '咖啡馆',
      bar: '酒吧',
      bakery: '烘焙店',
      meal_takeaway: '外卖',
      hair_salon: '美发沙龙',
      nail_salon: '美甲沙龙',
      spa: 'SPA',
      gym: '健身房',
      dentist: '牙科',
      car_repair: '汽车维修',
      florist: '花店',
      pet_store: '宠物用品店',
      book_store: '书店',
    },

    failures: {
      criteria_too_broad: '请补充类别或关键词，仅有地点无法说明要找什么。',
      location_not_found: 'Google 无法识别该地点，请检查拼写。',
      unknown_category: '服务器不接受该类别。',
      invalid_rating_range: '最低评分高于最高评分。',
      invalid_request: '部分条件超出可接受范围。',
      provider_unavailable: 'Google 没有响应，请稍后重试。',
      network: '无法连接到 API。',
      status: (status: number) => `请求失败（${status}）。`,
      unknown: '发生错误。',
    },

    search: {
      location: '地点',
      locationPlaceholder: '邮编、城市或地址',
      radius: '范围（米）',
      category: '类别',
      anyCategory: '不限',
      textQuery: '关键词',
      textQueryPlaceholder: 'Sushi Mura omakase',
      ratingMin: '最低评分',
      ratingMax: '最高评分',
      maxReviews: '评价数上限',
      submit: '搜索',
      submitting: '搜索中…',
      note: '必须填写类别或关键词，地点只说明在哪里找，不说明要找什么。',
      resolved: (place: string) => `搜索范围：${place} 附近`,
      funnel: (searched: number, matched: number) =>
        `已搜索 ${searched} 家商户 · 符合 ${matched} 家`,
      partial: 'Google 中途返回错误，这批结果并不完整。',
      truncated:
        '已达结果数量上限，Google 还有更多。请缩小搜索范围，或调高 LEAD_SEARCH_MAX_RESULTS。',
      empty:
        '没有符合的结果。评分与评价数条件是在 Google 返回结果之后才应用的，条件过严就会把列表滤空。',
      merchant: '商户',
      rating: '评分',
      reviews: '评价数',
      distance: '距离',
      uncategorised: '未分类',
      website: '网站',
      savedBadge: '已保存',
      save: '保存',
      saving: '保存中…',
      alreadySaved: (name: string) => `${name} 此前已保存，现有记录未更改。`,
    },

    saved: {
      merchant: '商户',
      status: '状态',
      savedOn: '保存日期',
      failed: '无法加载已保存的商户。',
      failedMore: '无法加载更多已保存的商户。',
      empty: '尚未保存任何商户。请先执行搜索。',
      loadMore: '加载更多',
      loadingMore: '加载中…',
    },

    copy: {
      copy: '复制',
      copied: '已复制',
      failed: '复制失败',
      copiedAnnouncement: '已复制到剪贴板',
      failedAnnouncement: '复制失败，请自行选取网址复制',
    },

    editor: {
      back: '← 返回',
      reviews: '条评价',
      asOf: (date: string) => `（数据日期：${date}）`,
      note: 'Google 提供简介与属性，这里其他字段都是 Google 无法得知的内容。两者合起来就是 AI 对这家商户所知道的全部。',
      about: '关于这家商户',
      offers: {
        title: '提供什么',
        caption: '这些内容决定了评价读起来像不像真的来过。',
      },
      voice: {
        title: '评价该怎么写',
        caption: '建议会从哪些角度撰写，以及可以使用哪些词语。',
      },
      instruction: {
        title: 'AI 指令',
      },
      fields: {
        businessSummary: {
          label: '商户简介',
          hint: '用两三句具体的话说明这是什么样的店。默认取自 Google 的编辑摘要；Google 没有时，则用类别与城市组成一句简述。',
        },
        products: { label: '商品' },
        services: { label: '服务' },
        menuItems: { label: '菜品' },
        sellingPoints: {
          label: '卖点',
          hint: '常客真正称赞的地方。默认取自 Google 的属性（堂食、外卖），但那些每家都有，请换成这家真正与众不同的地方。',
        },
        approvedKeywords: {
          label: '可用关键词',
          hint: '商户乐于看到出现在评价里的词语。只提供给模型参考，不会强制写入。',
        },
        experienceTopics: {
          label: '体验主题',
          hint: '每条建议一个角度，每批轮换，让三张卡片读起来像不同的评价。默认取自商户类别。',
        },
        customInstructions: {
          label: '自定义指令',
          hint: '告诉 AI 评价要遵循哪些自定义规则或风格。不要要求 AI 加入链接，那会导致输出无法通过校验。',
        },
      },
      onePerLine: '一行一项',
      noLinks: '不可包含链接或网址',
      save: '保存内容',
      saving: '保存中…',
      saved: '已保存',
      confirmation: '八个字段均已更新。',
      loadFailed: '无法加载这家商户。',
      saveFailed: '无法保存。',
      linkRejected:
        '自定义指令不可包含链接或网址。生成的评价会拒绝网址，这家商户的每一条建议都会失败。',
    },
  },
}
