import type { Locale } from './i18n'

/* The fortune corpus, and the draw.
 *
 * One entry per fortune holding all three translations, rather than three
 * arrays keyed by locale. The fortune is drawn once per page load and rendered
 * from whichever language is on screen, so a language switch has to translate
 * the same fortune rather than roll a new one — which only works while the
 * translations of one fortune travel together. Parallel arrays would let one
 * drift shorter and render `undefined` at the tail.
 *
 * Two rules, both from where this block sits — directly above a Google review.
 * Google forbids incentivised reviews AND soliciting positive ones, so neither
 * is a matter of taste:
 *
 *   1. Nothing promises luck, reward, or good fortune in return for anything.
 *   2. Nothing steers the review itself, in either direction. No kind words, no
 *      gentle speech, no forbearance, nothing saying the minute spent writing
 *      will be repaid, and nothing about patience or slowness — above a
 *      restaurant, that last one reads as a plea to excuse the wait.
 *
 * Rule 2 is the one that is easy to miss, and a Chinese couplet can break it
 * with a line that is not written down: 良言一句三冬暖 is completed by
 * 惡語傷人六月寒, and 海納百川 by 有容乃大, so both ask for a kind review in a
 * language the English half does not. **Check what an entry completes to**, not
 * only what it says.
 *
 * Read every new entry against both rules, in every language, before adding it.
 *
 * These are not customer data and not AI output: they are copy, in the same
 * sense as i18n/en.ts, and are translated for the same reason every other
 * customer-facing word is.
 */

export type Fortune = Record<Locale, string>

/* Typed as a non-empty tuple so `FORTUNES[0]` is a Fortune rather than
 * `Fortune | undefined` under noUncheckedIndexedAccess — which is what lets
 * the draw below narrow without an assertion. */
export const FORTUNES: [Fortune, ...Fortune[]] = [
  {
    en: 'A journey of a thousand miles begins with a single step.',
    'zh-Hant': '千里之行，始於足下。',
    'zh-Hans': '千里之行，始于足下。',
  },
  {
    en: 'The best time to plant a tree was twenty years ago; the second best is today.',
    'zh-Hant': '種樹最好的時候是二十年前，其次是今天。',
    'zh-Hans': '种树最好的时候是二十年前，其次是今天。',
  },
  {
    en: 'To know others is wisdom; to know yourself is clarity.',
    'zh-Hant': '知人者智，自知者明。',
    'zh-Hans': '知人者智，自知者明。',
  },
  {
    en: 'Still water runs deep.',
    'zh-Hant': '靜水流深。',
    'zh-Hans': '静水流深。',
  },
  {
    en: 'The person who moves a mountain begins by carrying away small stones.',
    'zh-Hant': '移山的人，先從搬走小石頭開始。',
    'zh-Hans': '移山的人，先从搬走小石头开始。',
  },
  {
    en: 'A true friend is a rare treasure.',
    'zh-Hant': '真正的朋友，是難得的珍寶。',
    'zh-Hans': '真正的朋友，是难得的珍宝。',
  },
  {
    en: 'Fall down seven times, stand up eight.',
    'zh-Hant': '跌倒七次，站起八次。',
    'zh-Hans': '跌倒七次，站起八次。',
  },
  {
    en: 'The wise adapt to circumstances as water takes the shape of its vessel.',
    'zh-Hant': '智者順勢而為，如水隨器成形。',
    'zh-Hans': '智者顺势而为，如水随器成形。',
  },
  {
    en: 'Only in the cold does one see the pine stays green.',
    'zh-Hant': '歲寒知松柏。',
    'zh-Hans': '岁寒知松柏。',
  },
  {
    en: 'A book is a garden carried in the pocket.',
    'zh-Hant': '書是袖中的花園。',
    'zh-Hans': '书是袖中的花园。',
  },
  {
    en: 'Read ten thousand books; walk ten thousand miles.',
    'zh-Hant': '讀萬卷書，行萬里路。',
    'zh-Hans': '读万卷书，行万里路。',
  },
  {
    en: 'Green comes from blue, yet is bluer than blue.',
    'zh-Hant': '青出於藍而勝於藍。',
    'zh-Hans': '青出于蓝而胜于蓝。',
  },
  {
    en: 'The great way is simple.',
    'zh-Hant': '大道至簡。',
    'zh-Hans': '大道至简。',
  },
  {
    en: 'The quieter the mind, the more it hears.',
    'zh-Hant': '心愈靜，聽得愈多。',
    'zh-Hans': '心愈静，听得愈多。',
  },
  {
    en: 'The moon does not compete; it simply shines.',
    'zh-Hant': '月亮不與人爭，只管發光。',
    'zh-Hans': '月亮不与人争，只管发光。',
  },
  {
    en: 'Study without thought leaves you lost; thought without study leaves you in peril.',
    'zh-Hant': '學而不思則罔，思而不學則殆。',
    'zh-Hans': '学而不思则罔，思而不学则殆。',
  },
  {
    en: 'Fallen leaves return to the root.',
    'zh-Hant': '落葉歸根。',
    'zh-Hans': '落叶归根。',
  },
  {
    en: 'To ask is to be a fool for a moment; never to ask is to be one for life.',
    'zh-Hant': '問者愚一時，不問者愚一世。',
    'zh-Hans': '问者愚一时，不问者愚一世。',
  },
  {
    en: 'The road is made by walking it.',
    'zh-Hant': '路是走出來的。',
    'zh-Hans': '路是走出来的。',
  },
  {
    en: 'The mind cannot do two things at once.',
    'zh-Hant': '一心不能二用。',
    'zh-Hans': '一心不能二用。',
  },
  {
    en: 'A tree grows toward the light.',
    'zh-Hant': '樹向光而生。',
    'zh-Hans': '树向光而生。',
  },
  {
    en: 'The best mirror is an old friend.',
    'zh-Hant': '最好的鏡子是老朋友。',
    'zh-Hans': '最好的镜子是老朋友。',
  },
  {
    en: 'A calm sea never made a skilled sailor.',
    'zh-Hant': '平靜的海，練不出好水手。',
    'zh-Hans': '平静的海，练不出好水手。',
  },
  {
    en: 'Dripping water hollows out stone.',
    'zh-Hant': '滴水穿石。',
    'zh-Hans': '滴水穿石。',
  },
]

/** One fortune, drawn uniformly.
 *
 *  Returns the whole entry rather than an index, so the caller holds every
 *  translation of the fortune it drew and a language change is a lookup rather
 *  than a second draw. Call it once per page load — see the note in Reviewer.
 */
export function drawFortune(): Fortune {
  const index = Math.floor(Math.random() * FORTUNES.length)

  // `?? FORTUNES[0]` rather than an assertion: in range for every Math.random()
  // in [0, 1), but a stub returning exactly 1 lands one past the end, and the
  // fallback costs less than the assertion it replaces.
  return FORTUNES[index] ?? FORTUNES[0]
}
