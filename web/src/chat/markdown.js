// Chat Markdown, as live renders it: markdown-it with raw HTML off, safe links
// only, images shown as their text. A card link on its title, [Title](CBK-####),
// opens the card in-app and shows only the title. A bare CBK-#### (older replies,
// the cook's own messages) still becomes a link, except inside code.
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({ html: false, breaks: true, linkify: false })
const CARD_HREF = /^(?:\/recipes\/)?(CBK-\d{4,})$/
md.validateLink = (href) => CARD_HREF.test(href) || /^(https?:|mailto:|\/(?!\/)|#)/i.test(href)
md.renderer.rules.image = (tokens, i) => md.utils.escapeHtml(tokens[i].content)
md.renderer.rules.link_open = (tokens, i, options, env, self) => {
  if (env) env.linkDepth = (env.linkDepth || 0) + 1
  const card = CARD_HREF.exec(tokens[i].attrGet('href') || '')
  if (card) {
    // In-app: the transcript routes data-recipe; no new tab.
    tokens[i].attrSet('href', '/recipes/' + card[1])
    tokens[i].attrSet('class', 'cbk cbk-title')
    tokens[i].attrSet('data-recipe', card[1])
    return self.renderToken(tokens, i, options)
  }
  tokens[i].attrSet('target', '_blank')
  tokens[i].attrSet('rel', 'noopener noreferrer')
  return self.renderToken(tokens, i, options)
}
md.renderer.rules.link_close = (tokens, i, options, env, self) => {
  if (env) env.linkDepth = Math.max(0, (env.linkDepth || 0) - 1)
  return self.renderToken(tokens, i, options)
}

const RECIPE_ID = /\b(CBK-\d{4,})\b/g
// linkDepth walks the token stream once. Scanning every earlier token from
// each text rule was quadratic in the length of the message.
md.renderer.rules.text = (tokens, i, options, env) => {
  const safe = md.utils.escapeHtml(tokens[i].content)
  if (env && env.linkDepth) return safe
  return safe.replace(RECIPE_ID, '<a class="cbk" href="/recipes/$1" data-recipe="$1">$1</a>')
}

const renderBlocks = md.renderer.render.bind(md.renderer)
md.renderer.render = function (tokens, options, env) {
  if (env) env.linkDepth = 0
  return renderBlocks(tokens, options, env)
}

export function renderChatMarkdown(text) {
  return md.render(String(text || ''))
}
