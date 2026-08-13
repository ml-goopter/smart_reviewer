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
    skip: '自己撰寫',
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
    capReached: '建議已達次數上限。',
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

  /* The internal crawler. The register changes here: this is a colleague's
   * tool, so it is terse and imperative where the customer screens are polite,
   * and it keeps the operator's own vocabulary — 商戶 for a prospect rather
   * than the customer-facing 店家, because the operator is looking at a row in
   * a table, not at somewhere they just ate. */
  leads: {
    title: '商戶開發工具',
    viewsLabel: '商戶開發工具檢視',
    tabs: {
      search: '搜尋',
      saved: '已儲存',
    },
    loading: '載入中…',
    edit: '編輯',
    copyUrl: '複製網址',
    noUrl: '無網址',

    categories: {
      restaurant: '餐廳',
      cafe: '咖啡廳',
      bar: '酒吧',
      bakery: '烘焙坊',
      meal_takeaway: '外帶',
      hair_salon: '美髮沙龍',
      nail_salon: '美甲沙龍',
      spa: 'SPA',
      gym: '健身房',
      dentist: '牙醫',
      car_repair: '汽車維修',
      florist: '花店',
      pet_store: '寵物用品店',
      book_store: '書店',
    },

    failures: {
      criteria_too_broad: '請加上類別或關鍵字，只有地點無法說明要找什麼。',
      location_not_found: 'Google 無法辨識這個地點，請檢查拼字。',
      unknown_category: '伺服器不接受這個類別。',
      invalid_rating_range: '最低評分高於最高評分。',
      invalid_request: '部分條件超出可接受範圍。',
      provider_unavailable: 'Google 沒有回應，請稍後再試。',
      network: '無法連線到 API。',
      status: (status: number) => `請求失敗（${status}）。`,
      unknown: '發生錯誤。',
    },

    search: {
      location: '地點',
      locationPlaceholder: '郵遞區號、城市或地址',
      radius: '範圍（公尺）',
      category: '類別',
      anyCategory: '不限',
      textQuery: '關鍵字',
      textQueryPlaceholder: 'Sushi Mura omakase',
      ratingMin: '最低評分',
      ratingMax: '最高評分',
      maxReviews: '評論數上限',
      submit: '搜尋',
      submitting: '搜尋中…',
      note: '必須填寫類別或關鍵字，地點只說明在哪裡找，不說明要找什麼。',
      resolvedBefore: '搜尋範圍：',
      resolvedAfter: ' 附近',
      funnel: (searched: number, matched: number) =>
        `已搜尋 ${searched} 筆商戶 · 符合 ${matched} 筆`,
      partial: 'Google 中途回傳錯誤，這批結果並不完整。',
      truncated:
        '已達結果數量上限，Google 還有更多。請縮小搜尋範圍，或調高 LEAD_SEARCH_MAX_RESULTS。',
      empty:
        '沒有符合的結果。評分與評論數的條件是在 Google 回傳結果之後才套用的，條件太嚴就會把清單濾空。',
      merchant: '商戶',
      rating: '評分',
      reviews: '評論數',
      distance: '距離',
      /** The cell under it. A row of "1.2 km" under 距離 is the one place the
       *  table was still half-English. */
      metres: (value: number) => `${value} 公尺`,
      kilometres: (value: string) => `${value} 公里`,
      uncategorised: '未分類',
      website: '網站',
      savedBadge: '已儲存',
      save: '儲存',
      saving: '儲存中…',
      alreadySaved: (name: string) => `${name} 先前已儲存，現有資料未變更。`,
      notSubscribed: (name: string) =>
        `${name}：尚未訂閱，訂閱後此網址才能開啟`,
    },

    saved: {
      merchant: '商戶',
      subscription: '訂閱',
      savedOn: '儲存日期',
      failed: '無法載入已儲存的商戶。',
      failedMore: '無法載入更多已儲存的商戶。',
      empty: '尚未儲存任何商戶。請先搜尋。',
      loadMore: '載入更多',
      loadingMore: '載入中…',
    },

    subscription: {
      heading: '訂閱',
      notSubscribed: '未訂閱',
      expires: '到期日',
      subscribe: (days: number) => `訂閱 ${days} 天`,
      renew: (days: number) => `續訂 ${days} 天`,
      suspend: '暫停',
      resume: '恢復',
      failed: '無法更新訂閱。',
      renewNote: '續訂會在剩餘天數上累加，不會取代原有天數。',
      suspendedNote: '已暫停。訂閱期仍在計算，只有「恢復」才會重新開啟網址。',
    },

    copy: {
      copy: '複製',
      copied: '已複製',
      failed: '複製失敗',
      copiedAnnouncement: '已複製到剪貼簿',
      failedAnnouncement: '複製失敗，請自行選取網址複製',
    },

    editor: {
      back: '← 返回',
      reviews: '則評論',
      asOf: (date: string) => `（資料日期：${date}）`,
      note: 'Google 提供簡介與屬性，這裡其他欄位都是 Google 無法得知的內容。兩者合起來就是 AI 對這家商戶所知道的全部。',
      about: '關於這家商戶',
      offers: {
        title: '提供什麼',
        caption: '這些內容決定了評論讀起來像不像真的來過。',
      },
      voice: {
        title: '評論該怎麼寫',
        caption: '建議會從哪些角度撰寫，以及可以使用哪些字詞。',
      },
      instruction: {
        title: 'AI 指示',
      },
      fields: {
        businessSummary: {
          label: '商戶簡介',
          hint: '用兩三句具體的話說明這是什麼樣的店。預設帶入 Google 的編輯摘要；Google 沒有時，則用類別與城市組成一句簡述。',
        },
        products: { label: '商品' },
        services: { label: '服務' },
        menuItems: { label: '菜色' },
        sellingPoints: {
          label: '賣點',
          hint: '常客真正稱讚的地方。預設帶入 Google 的屬性（內用、外帶），但那些每家都有，請換成這家真正與眾不同的地方。',
        },
        approvedKeywords: {
          label: '可用關鍵字',
          hint: '商戶樂見出現在評論裡的字詞。只提供給模型參考，不會強制寫入。',
        },
        experienceTopics: {
          label: '體驗主題',
          hint: '每則建議一個角度，每批輪換，讓三張卡片讀起來像不同的評論。預設帶入自商戶類別。',
        },
        customInstructions: {
          label: '自訂指示',
          hint: '告訴 AI 評論要遵循哪些自訂規則或風格。不要要求 AI 加入連結，那會導致產出無法通過驗證。',
        },
      },
      onePerLine: '一行一項',
      noLinks: '不可包含連結或網址',
      save: '儲存內容',
      saving: '儲存中…',
      saved: '已儲存',
      confirmation: '八個欄位皆已更新。',
      loadFailed: '無法載入這家商戶。',
      saveFailed: '無法儲存。',
      linkRejected:
        '自訂指示不可包含連結或網址。產生的評論會拒絕網址，這家商戶的每一則建議都會失敗。',
    },
  },
}
